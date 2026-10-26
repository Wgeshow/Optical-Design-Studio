"""Eigenfree, complex128 Fourier Maxwell scattering on NumPy or CuPy.

Native GetEigenfreeOperators supplies the exact S4 constitutive matrices. A
bounded thin-slice Taylor expansion is converted to scattering before doubling;
no growing thick-layer transfer matrix or modal eigendecomposition is formed.
All wavelengths and Fourier orders are solved directly. Internal fields use
two-sided scattering, so evanescent components never need backward propagation.
"""
from dataclasses import dataclass
from collections import OrderedDict
import math
import numpy as np


def _matrix(value, n):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return np.frombuffer(value, np.complex128).reshape(n, n, order='F')
    return np.asarray(value, np.complex128).reshape(n, n)


def mirror_projectors(g):
    """Real orthonormal H/rotated-E projectors (++),(-+),(+-),(--)."""
    g = np.asarray(g, dtype=np.int64)
    n = len(g)
    lookup = {tuple(v): i for i, v in enumerate(g)}
    if len(lookup) != n:
        raise ValueError('Duplicate Fourier orders')
    sectors = []
    for px, py in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        columns = []
        for component, (sx, sy) in enumerate(((1, -1), (-1, 1))):
            seen = set()
            for seed, (gx, gy) in enumerate(g):
                if seed in seen:
                    continue
                orbit = [lookup.get((int(x), int(y))) for x, y in
                         ((gx, gy), (-gx, gy), (gx, -gy), (-gx, -gy))]
                if None in orbit:
                    raise ValueError('Fourier set is not closed under both mirrors')
                seen.update(orbit)
                vector = np.zeros(2*n)
                for index, weight in zip(orbit, (1, px*sx, py*sy, px*py*sx*sy)):
                    vector[component*n+index] += weight
                norm = np.linalg.norm(vector)
                if norm:
                    columns.append(vector/norm)
        sectors.append(np.stack(columns, axis=1) if columns else np.zeros((2*n, 0)))
    return sectors


@dataclass
class Scattering:
    # b_left = r*a_left + u*b_right; a_right = t*a_left + v*b_right
    r: object
    u: object
    t: object
    v: object


class EigenfreeSolver:
    """One resident batch with the same layer count and Fourier order count."""
    def __init__(self, payloads, backend='cupy', slice_norm=0.5, degree=8, symmetry=False):
        if not payloads:
            raise ValueError('An eigenfree batch must not be empty')
        if backend == 'cupy':
            import cupy as xp
        elif backend == 'numpy':
            xp = np
        else:
            raise ValueError('backend must be numpy or cupy')
        if not 0 < slice_norm <= 0.5 or degree < 8:
            raise ValueError('Accuracy requires slice_norm <= 0.5 and degree >= 8')
        self.xp, self.backend = xp, backend
        self.payloads = payloads
        self._coefficient_cache = OrderedDict()
        self.batch, self.n = len(payloads), int(payloads[0]['n'])
        self.m = 2*self.n
        self.slice_norm, self.degree = slice_norm, degree
        self.diagnostics = {'backend': backend, 'dtype': 'complex128',
                            'eigendecompositions': 0, 'doublings': [],
                            'wavelengths': self.batch, 'retained_orders': self.n}
        nl = len(payloads[0]['layers'])
        if nl < 2:
            raise ValueError('At least two exterior layers are required')
        if any(int(p['n']) != self.n or len(p['layers']) != nl for p in payloads):
            raise ValueError('Batch topology and Fourier count must match')
        if any(p['layers'][i]['thickness'] != 0 for p in payloads for i in (0, -1)):
            raise NotImplementedError('Eigenfree exterior reference layers must have zero thickness')
        self.I = xp.broadcast_to(xp.eye(self.m, dtype=xp.complex128),
                                 (self.batch, self.m, self.m))
        self.Z = xp.zeros_like(self.I)
        self.physical_I, self.projector = self.I, None
        self.omega = xp.asarray([p['omega'] for p in payloads], dtype=xp.complex128)
        if bool(xp.any(self.omega.imag != 0)) or bool(xp.any(self.omega.real <= 0)):
            raise ValueError('This backend requires positive real frequency')
        self.kx = xp.asarray([p['kx'] for p in payloads], dtype=xp.float64)
        self.ky = xp.asarray([p['ky'] for p in payloads], dtype=xp.float64)
        self.k = xp.concatenate((self.kx, self.ky), axis=-1)
        self.rotk = xp.concatenate((self.ky, -self.kx), axis=-1)
        self.kk = xp.zeros_like(self.I)
        idx = xp.arange(self.n)
        for i, ki in enumerate((self.kx, self.ky)):
            for j, kj in enumerate((self.kx, self.ky)):
                self.kk[:, i*self.n+idx, j*self.n+idx] = ki*kj
        self.layers = []
        for li in range(nl):
            ls = [p['layers'][li] for p in payloads]
            eta = xp.asarray(np.stack([_matrix(l['epsilon_inv'], self.n) for l in ls]))
            eps2 = xp.asarray(np.stack([_matrix(l['epsilon2'], self.m) for l in ls]))
            kp = self.omega[:, None, None]**2*self.I
            for i, ki in enumerate((self.ky, -self.kx)):
                for j, kj in enumerate((self.ky, -self.kx)):
                    kp[:, i*self.n:(i+1)*self.n, j*self.n:(j+1)*self.n] -= ki[:, :, None]*eta*kj[:, None, :]
            P = kp/self.omega[:, None, None]
            Q = self.omega[:, None, None]*eps2-self.kk/self.omega[:, None, None]
            self.layers.append({'P': P, 'Q': Q, 'eta': eta, 'kp': kp,
                'thickness': xp.asarray([l['thickness'] for l in ls], dtype=xp.float64),
                'uniform': all(l.get('uniform', False) and l.get('epsilon') is not None for l in ls)})
        for li in (0, nl-1):
            if any(not p['layers'][li].get('uniform', False) or p['layers'][li].get('epsilon') is None for p in payloads):
                raise ValueError('Exterior layers must be uniform scalar materials')
        self.regular_ports = any(bool(xp.any(self._vertical_wavevector(li) == 0))
                                 for li in (0, nl-1))
        if self.regular_ports:
            self.Hleft, self.Eleft, self.qleft = self._radiation_basis(0)
            self.Hright, self.Eright, self.qright = self._radiation_basis(nl-1)
        else:
            self.Yleft, self.qleft = self._admittance(0)
            self.Yright, self.qright = self._admittance(nl-1)
            self.Hleft, self.Eleft = self.I, self.Yleft
            self.Hright, self.Eright = self.I, self.Yright
        self.physical_Hleft, self.physical_Eleft = self.Hleft, self.Eleft
        self.physical_Hright, self.physical_Eright = self.Hright, self.Eright
        self.diagnostics['regular_radiation_ports'] = self.regular_ports
        self.diagnostics['cutoff_orders'] = [self._host(q[:, :self.n] == 0).sum(axis=1).tolist()
                                               for q in (self.qleft, self.qright)]
        self.incident_left = xp.zeros((self.batch, self.m, 1), dtype=xp.complex128)
        self.incident_right = xp.zeros_like(self.incident_left)
        for bi, payload in enumerate(payloads):
            value = payload['excitation_h']
            a = np.frombuffer(value, np.complex128) if isinstance(value, (bytes, bytearray, memoryview)) else np.asarray(value, np.complex128)
            target = self.incident_right if payload.get('backwards', False) else self.incident_left
            target[bi, :, 0] = xp.asarray(a)
        if self.regular_ports:
            self.incident_left = self._port_excitation(self.incident_left, 0, self.qleft)
            self.incident_right = self._port_excitation(self.incident_right, nl-1, self.qright)
        self.diagnostics['symmetry_requested'] = bool(symmetry)
        if symmetry:
            self._try_symmetry()
        self.diagnostics['solver_dimension'] = self.m
        self.pieces = [self._left_port()]
        self.pieces += [self._slab(i, self.layers[i]['thickness']) for i in range(1, nl-1)]
        self.pieces.append(self._right_port())
        self.prefix = [self.identity()]
        for piece in self.pieces:
            self.prefix.append(self.star(self.prefix[-1], piece))
        self.suffix = None
        self.total = self.prefix[-1]
        self.reflected = self.total.r@self.incident_left+self.total.u@self.incident_right
        self.transmitted = self.total.t@self.incident_left+self.total.v@self.incident_right
        if not bool(xp.all(xp.isfinite(self.reflected))) or not bool(xp.all(xp.isfinite(self.transmitted))):
            raise FloatingPointError('Nonfinite eigenfree boundary solution')

    def _host(self, value):
        return self.xp.asnumpy(value) if self.backend == 'cupy' else np.asarray(value)

    def _try_symmetry(self):
        """Reduce only with exact native geometry eligibility and numerical proof."""
        if not all(p.get('mirror_eligible', False) for p in self.payloads):
            self.diagnostics['symmetry_reason'] = 'native geometry guard declined'
            return
        try:
            sectors = mirror_projectors(self.payloads[0]['G'])
        except ValueError as exc:
            self.diagnostics['symmetry_reason'] = str(exc)
            return
        if any(not np.array_equal(p['G'], self.payloads[0]['G']) for p in self.payloads[1:]):
            self.diagnostics['symmetry_reason'] = 'batch Fourier ordering differs'
            return
        excitation = self._host(self.xp.concatenate((self.incident_left, self.incident_right), axis=-1))
        norm = max(float(np.max(np.abs(excitation))), np.finfo(float).tiny)
        # Never discard a physically nonzero polarization, however small.
        active = [u for u in sectors if u.shape[1] and np.any((u.T@excitation) != 0)]
        if not active:
            self.diagnostics['symmetry_reason'] = 'no active excitation'
            return
        u = self.xp.asarray(np.concatenate(active, axis=1), dtype=self.xp.complex128)
        if u.shape[1] == self.m:
            self.diagnostics['symmetry_reason'] = 'all sectors excited'
            return
        def project(a):
            return u.T@a@u
        pending = []
        maximum = 0.
        for layer in self.layers:
            pair = []
            for name in ('P', 'Q'):
                a = layer[name]
                small = project(a)
                error = float(self.xp.max(self.xp.abs(a@u-u@small)))
                scale = max(float(self.xp.max(self.xp.abs(a))), np.finfo(float).tiny)
                maximum = max(maximum, error/scale)
                pair.append(small)
            pending.append(pair)
        for y in (self.Hleft, self.Eleft, self.Hright, self.Eright):
            small = project(y)
            maximum = max(maximum, float(self.xp.max(self.xp.abs(y@u-u@small)))/max(float(self.xp.max(self.xp.abs(y))), np.finfo(float).tiny))
        for a in (self.incident_left, self.incident_right):
            maximum = max(maximum, float(self.xp.max(self.xp.abs(a-u@(u.T@a))))/norm)
        self.diagnostics['symmetry_invariance_residual'] = maximum
        if maximum > 2e-13:
            self.diagnostics['symmetry_reason'] = 'operator or excitation invariance failed'
            return
        self.projector = u
        for layer, (P, Q) in zip(self.layers, pending):
            layer['P'], layer['Q'] = P, Q
        self.Hleft, self.Eleft = project(self.Hleft), project(self.Eleft)
        self.Hright, self.Eright = project(self.Hright), project(self.Eright)
        if not self.regular_ports:
            self.Yleft, self.Yright = self.Eleft, self.Eright
        self.incident_left = u.T@self.incident_left
        self.incident_right = u.T@self.incident_right
        self.m = u.shape[1]
        self.I = self.xp.broadcast_to(self.xp.eye(self.m, dtype=self.xp.complex128), (self.batch, self.m, self.m))
        self.Z = self.xp.zeros_like(self.I)
        self.diagnostics['symmetry_reason'] = 'exact geometry and invariant excited sectors'
        self.diagnostics['active_sector_dimensions'] = [v.shape[1] for v in active]

    def _lift(self, value):
        return self.projector@value if self.projector is not None else value

    def identity(self):
        return Scattering(self.Z, self.I, self.I, self.Z)

    def star(self, a, b):
        """Compose left network a and right network b via Redheffer product."""
        if a.r is self.Z and a.u is self.I and a.t is self.I and a.v is self.Z:
            return b
        if b.r is self.Z and b.u is self.I and b.t is self.I and b.v is self.Z:
            return a
        xp = self.xp
        rhs = xp.concatenate((b.r@a.t, b.u), axis=-1)
        sol = xp.linalg.solve(self.I-b.r@a.v, rhs)
        x, y = sol[..., :self.m], sol[..., self.m:]
        return Scattering(a.r+a.u@x, a.u@y,
                          b.t@(a.t+a.v@x), b.v+b.t@a.v@y)

    def _interface(self, yl, yr):
        sol = self.xp.linalg.solve(yl+yr, self.xp.concatenate((yl-yr, 2*yr), axis=-1))
        r, u = sol[..., :self.m], sol[..., self.m:]
        return Scattering(r, u, self.I+r, u-self.I)

    def _admittance(self, li):
        q = self._vertical_wavevector(li)
        if bool(self.xp.any(q == 0)):
            raise ValueError('Uniform slab requires regular propagation at its diffraction threshold')
        qq = self.xp.concatenate((q, q), axis=-1)
        return self.layers[li]['kp']/self.omega[:, None, None]/qq[:, None, :], qq

    def _vertical_wavevector(self, li):
        xp = self.xp
        eps = xp.asarray([p['layers'][li]['epsilon'] for p in self.payloads], dtype=xp.complex128)
        frequency_term = self.omega[:, None]**2*eps[:, None]
        lateral_term = self.kx**2+self.ky**2
        squared = frequency_term-lateral_term
        # Cancellation in k_z^2 at an exact Rayleigh threshold is limited by
        # the roundoff of its two terms. Preserve zero rather than inserting a
        # small k_z or changing the frequency/materials.
        roundoff = 8*np.finfo(float).eps*(xp.abs(frequency_term)+lateral_term)
        squared = xp.where((eps.imag[:, None] == 0) & (xp.abs(squared) <= roundoff), 0, squared)
        q = xp.sqrt(squared)
        q = xp.where((q.imag < 0) | ((q.imag == 0) & (q.real < 0)), -q, q)
        return q

    def _parallel_projector(self):
        xp = self.xp
        squared = self.kx**2+self.ky**2
        denominator = xp.where(squared == 0, 1, squared)
        return squared, denominator

    def _radiation_basis(self, li):
        """Finite outgoing H/E columns at k_z=0, with no division by k_z.

        With J the projector onto transverse k in magnetic coordinates,
        H=(I-J)+(q/omega)J and rotated E=(q/(epsilon*omega))(I-J)+J.
        These obey Maxwell's equations including the grazing limit. The
        magnetic-parallel wave uses its finite electric amplitude as its port
        coordinate; a grazing wave therefore has finite E and zero normal flux.
        """
        xp = self.xp
        q = self._vertical_wavevector(li)
        eps = xp.asarray([p['layers'][li]['epsilon'] for p in self.payloads], dtype=xp.complex128)
        if bool(xp.any(eps == 0)):
            raise ValueError('Zero exterior permittivity is not supported')
        _, denominator = self._parallel_projector()
        H, E = xp.zeros_like(self.I), xp.zeros_like(self.I)
        idx = xp.arange(self.n)
        hparallel, eperp = q/self.omega[:, None], q/(eps*self.omega)[:, None]
        for i, ki in enumerate((self.kx, self.ky)):
            for j, kj in enumerate((self.kx, self.ky)):
                parallel = ki*kj/denominator
                perp = float(i == j)-parallel
                H[:, i*self.n+idx, j*self.n+idx] = perp+hparallel*parallel
                E[:, i*self.n+idx, j*self.n+idx] = eperp*perp+parallel
        qq = xp.concatenate((q, q), axis=-1)
        return H, E, qq

    def _port_excitation(self, h, li, q):
        xp = self.xp
        _, denominator = self._parallel_projector()
        hx, hy = h[:, :self.n, 0], h[:, self.n:, 0]
        dot = (self.kx*hx+self.ky*hy)/denominator
        parallel = xp.concatenate((self.kx*dot, self.ky*dot), axis=-1)[..., None]
        grazing = q[..., None] == 0
        if bool(xp.any(grazing & (xp.abs(parallel) > 64*np.finfo(float).eps*xp.max(xp.abs(h))))):
            raise ValueError('A grazing incident wave cannot supply positive normal power')
        divisor = xp.where(q == 0, 1, q)
        scale = xp.where(q == 0, 0, self.omega[:, None]/divisor)[..., None]
        return h-parallel+scale*parallel

    def _left_port(self):
        if not self.regular_ports:
            return self._interface(self.Yleft, self.I)
        H, E = self.Hleft, self.Eleft
        sol = self.xp.linalg.solve(H+E, self.xp.concatenate((E-H, 2*self.I), axis=-1))
        r, u = sol[..., :self.m], sol[..., self.m:]
        return Scattering(r, u, H@(self.I+r), H@u-self.I)

    def _right_port(self):
        if not self.regular_ports:
            return self._interface(self.I, self.Yright)
        H, E = self.Hright, self.Eright
        sol = self.xp.linalg.solve(H+E, self.xp.concatenate((2*self.I, E-H), axis=-1))
        t, v = sol[..., :self.m], sol[..., self.m:]
        return Scattering(H@t-self.I, H@(self.I+v), t, v)

    def _slab(self, li, thickness):
        xp = self.xp
        P, Q = self.layers[li]['P'], self.layers[li]['Q']
        thickness = xp.broadcast_to(xp.asarray(thickness, dtype=xp.float64), (self.batch,))
        if bool(xp.any(thickness < 0)):
            raise ValueError('Layer depth/thickness must be nonnegative')
        if bool(xp.all(thickness == 0)):
            return self.identity()
        if self.layers[li]['uniform']:
            try:
                return self._uniform_slab(li, thickness)
            except ValueError:
                # At an internal diffraction threshold PIM remains regular.
                pass
        bound = xp.maximum(xp.max(xp.sum(xp.abs(P), axis=-1), axis=-1),
                           xp.max(xp.sum(xp.abs(Q), axis=-1), axis=-1))*thickness
        maximum = float(xp.max(bound))
        squarings = max(0, math.ceil(math.log2(maximum/self.slice_norm))) if maximum else 0
        self.diagnostics['doublings'].append(squarings)
        d = thickness[:, None, None]/2**squarings
        X, Y = -(d*d)*(Q@P), -(d*d)*(P@Q)
        cq, cp = self.I.copy(), self.I.copy()
        sq, sp = self.I.copy(), self.I.copy()
        tq, tp = self.I.copy(), self.I.copy()
        for k in range(1, self.degree+1):
            tq = (tq@X)/((2*k-1)*(2*k))
            tp = (tp@Y)/((2*k-1)*(2*k))
            cq, cp = cq+tq, cp+tp
            sq, sp = sq+tq/(2*k+1), sp+tp/(2*k+1)
        he, eh = 1j*d*(Q@sp), 1j*d*(P@sq)
        ba = (cq+he-eh-cp)/2
        bb = (cq-he-eh+cp)/2
        sol = xp.linalg.solve(bb, xp.concatenate((-ba, self.I), axis=-1))
        r, u = sol[..., :self.m], sol[..., self.m:]
        # Homogeneous Maxwell's generator anticommutes with diag(I,-I).
        # Reversing z therefore exchanges identical reference ports: r=v,
        # u=t, without assuming reciprocity or that P and Q commute.
        s = Scattering(r, u, u, r)
        for _ in range(squarings):
            s = self._double_slab(s)
        return s

    def _double_slab(self, s):
        """Identical homogeneous slabs, each with equal I-admittance ports."""
        sol = self.xp.linalg.solve(self.I-s.r@s.r,
                    self.xp.concatenate((s.r@s.t, s.t), axis=-1))
        reflection = s.r+s.t@sol[..., :self.m]
        transmission = s.t@sol[..., self.m:]
        return Scattering(reflection, transmission, transmission, reflection)

    def _uniform_slab(self, li, thickness):
        """Analytic uniform layers using independent 2x2 Fourier blocks."""
        xp = self.xp
        admittance, q = self._admittance(li)
        idx = xp.arange(self.n)
        y = xp.empty((self.batch, self.n, 2, 2), dtype=xp.complex128)
        for i in range(2):
            for j in range(2):
                y[..., i, j] = admittance[:, i*self.n+idx, j*self.n+idx]
        eye = xp.broadcast_to(xp.eye(2, dtype=xp.complex128), y.shape)
        r = xp.linalg.solve(eye+y, eye-y)
        phase = xp.exp(1j*q[:, :self.n]*thickness[:, None])[..., None, None]
        rr = r@r
        denominator = eye-rr*phase**2
        result = xp.linalg.solve(denominator, xp.concatenate((r*(1-phase**2), (eye-rr)*phase), axis=-1))
        rb, tb = result[..., :2], result[..., 2:]
        reflection, transmission = xp.zeros_like(self.physical_I), xp.zeros_like(self.physical_I)
        for i in range(2):
            for j in range(2):
                reflection[:, i*self.n+idx, j*self.n+idx] = rb[..., i, j]
                transmission[:, i*self.n+idx, j*self.n+idx] = tb[..., i, j]
        if self.projector is not None:
            reflection = self.projector.T@reflection@self.projector
            transmission = self.projector.T@transmission@self.projector
        return Scattering(reflection, transmission, transmission, reflection)

    def _cut(self, left, right):
        rhs = left.t@self.incident_left+left.v@right.u@self.incident_right
        a = self.xp.linalg.solve(self.I-left.v@right.r, rhs)
        b = right.r@a+right.u@self.incident_right
        return a, b

    def _ensure_suffix(self):
        # Spectra need only the forward cascade. Build reverse networks lazily
        # while retaining the complete field-recovery capability.
        if self.suffix is None:
            self.suffix = [None]*(len(self.pieces)+1)
            self.suffix[-1] = self.identity()
            for i in range(len(self.pieces)-1, -1, -1):
                self.suffix[i] = self.star(self.pieces[i], self.suffix[i+1])

    def coefficients(self, layer_index, depth):
        """Return [wavelength, Fourier order, Ex/Ey/Ez/Hx/Hy/Hz].

        Depth is measured from the selected layer's left boundary. Exterior
        depth is relative to its adjacent stack boundary and may be negative.
        """
        xp, li = self.xp, int(layer_index)
        key = (li, float(depth)) if np.isscalar(depth) else None
        if key is not None and key in self._coefficient_cache:
            self._coefficient_cache.move_to_end(key)
            return self._coefficient_cache[key].copy()
        if li == 0:
            phase = xp.exp(1j*self.qleft*xp.asarray(depth)[..., None])
            a, b = self._lift(self.incident_left)*phase[..., None], self._lift(self.reflected)/phase[..., None]
            h, e = self.physical_Hleft@(a+b), self.physical_Eleft@(a-b)
        elif li == len(self.layers)-1:
            phase = xp.exp(1j*self.qright*xp.asarray(depth)[..., None])
            a, b = self._lift(self.transmitted)*phase[..., None], self._lift(self.incident_right)/phase[..., None]
            h, e = self.physical_Hright@(a+b), self.physical_Eright@(a-b)
        else:
            self._ensure_suffix()
            z = xp.broadcast_to(xp.asarray(depth, dtype=xp.float64), (self.batch,))
            if bool(xp.any(z < 0)) or bool(xp.any(z > self.layers[li]['thickness']+1e-13)):
                raise ValueError('Requested depth outside layer')
            left = self.star(self.prefix[li], self._slab(li, z))
            right = self.star(self._slab(li, xp.maximum(0, self.layers[li]['thickness']-z)), self.suffix[li+1])
            a, b = self._cut(left, right)
            h, e = self._lift(a+b), self._lift(a-b)
        hx, hy = h[:, :self.n, 0], h[:, self.n:, 0]
        ey, ex = -e[:, :self.n, 0], e[:, self.n:, 0]
        ez = (self.layers[li]['eta']@(self.ky*hx-self.kx*hy)[..., None])[..., 0]/self.omega[:, None]
        hz = (self.kx*ey-self.ky*ex)/self.omega[:, None]
        result = xp.stack((ex, ey, ez, hx, hy, hz), axis=-1)
        if not bool(xp.all(xp.isfinite(result))):
            raise FloatingPointError('Nonfinite eigenfree field coefficients')
        host = self._host(result)
        if key is not None:
            self._coefficient_cache[key] = host.copy()
            if len(self._coefficient_cache) > 8:
                self._coefficient_cache.popitem(last=False)
        return host

    def fields(self, layer_index, depth, xy):
        coefficients = self.xp.asarray(self.coefficients(layer_index, depth))
        xy = self.xp.asarray(xy, dtype=self.xp.float64)
        phase = self.xp.exp(1j*(self.kx[:, None, :]*xy[None, :, 0, None]+self.ky[:, None, :]*xy[None, :, 1, None]))
        return self._host(phase@coefficients)

    def port_amplitudes(self):
        left = self.physical_Hleft@self._lift(self.xp.concatenate((self.incident_left, self.reflected), axis=-1))
        right = self.physical_Hright@self._lift(self.xp.concatenate((self.transmitted, self.incident_right), axis=-1))
        return self._host(self.xp.concatenate((left, right), axis=-1))

    def _flux(self, a, h, e):
        return self.xp.real(self.xp.sum(self.xp.conj(h@a)*(e@a), axis=(-2, -1)))

    def rta(self):
        """Power ratios for a single incident side, requiring lossless exteriors."""
        if any(complex(p['layers'][i]['epsilon']).imag != 0 for p in self.payloads for i in (0, -1)):
            raise ValueError('R/T normalization currently requires lossless exterior materials')
        fl = self._flux(self.incident_left, self.Hleft, self.Eleft)
        fr = self._flux(self.incident_right, self.Hright, self.Eright)
        reflected = self._flux(self.reflected, self.Hleft, self.Eleft)
        transmitted = self._flux(self.transmitted, self.Hright, self.Eright)
        backwards = self.xp.asarray([p.get('backwards', False) for p in self.payloads])
        incoming = fl+fr
        if bool(self.xp.any(incoming <= 0)):
            raise ValueError('Positive incoming propagating power is required')
        r = self.xp.where(backwards, transmitted, reflected)/incoming
        t = self.xp.where(backwards, reflected, transmitted)/incoming
        return self._host(self.xp.stack((r, t, 1-r-t), axis=-1))


def solve_batch(payloads, backend='cupy', **kwargs):
    return EigenfreeSolver(payloads, backend=backend, **kwargs)
