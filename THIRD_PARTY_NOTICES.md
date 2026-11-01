# Additional notices for Optical Design Studio 1.4.0-alpha.6

The native scientific plotting runtime includes PyQtGraph and its Colorama dependency. The following notices supplement the existing application, native S4, Qt/PyQt, numerical, geometry, machine-learning, and optional runtime notices supplied in **THIRD_PARTY_LICENSES** and the corresponding source.

| Component | Version | License | Full notice |
| --- | --- | --- | --- |
| PyQtGraph | 0.14.0 | MIT | THIRD_PARTY_LICENSES/PyQtGraph-0.14.0/LICENSE.txt |
| Colorama | 0.4.6 | BSD 3-Clause | THIRD_PARTY_LICENSES/Colorama-0.4.6/LICENSE.txt |
| DEVSIM | 2.11.0 | Apache 2.0 and bundled component notices | THIRD_PARTY_LICENSES/DEVSIM-2.11.0/LICENSE and NOTICE |
| CuPy CUDA 13 | 14.2.0 | MIT and bundled component notices | THIRD_PARTY_LICENSES/GPU/cupy_cuda13x-14.2.0.dist-info/licenses/ |
| Fastrlock | 0.8.3 | MIT | THIRD_PARTY_LICENSES/GPU/fastrlock-0.8.3.dist-info/LICENSE |
| CUDA Pathfinder | 1.8.3 | Apache 2.0 | THIRD_PARTY_LICENSES/GPU/cuda_pathfinder-1.8.3.dist-info/licenses/LICENSE |

The optional GPU payload also retains NVIDIA CUDA 13 component license texts under **THIRD_PARTY_LICENSES/GPU/nvidia_*.dist-info/licenses/**. The complete matching distribution metadata and license files remain beside the bundled GPU runtime. CUDA 11 runtime notices remain under **THIRD_PARTY_LICENSES/NVIDIA**. DEVSIM's NOTICE includes its AMD and UMFPACK notices; those components are used by permission under their supplied terms. Their copyright and source-availability notices are retained verbatim.

MPB, Meep, Legume, Sesame and Gmsh workflows use separately configured external environments. Those engines and their licenses belong to their respective installations; selecting one in the user interface does not install it into this portable package.

The complete copyright, redistribution terms, and disclaimers are retained verbatim from the included distributions. The license texts apply to their respective components and do not grant rights to unrelated components.

The public Silicon tutorial is an application-generated S4 calculation using explicitly stated constant optical indices. Its included inputs, scientific data, and provenance describe that example; they do not establish measured-material accuracy or convergence for other designs. If an external optical-constant dataset is separately imported, its original source attribution and terms still apply.
