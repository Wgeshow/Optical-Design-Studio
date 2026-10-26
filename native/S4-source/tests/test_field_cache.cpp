// Native API invalidation coverage for setters not exposed by Python.
#include "S4.h"
#include <cmath>
#include <cstdio>
#include <vector>

static int compare_clone(S4_Simulation *s){
	const double z[] = {.01, .11, .23};
	std::vector<double> a(12*3*s->n_G), b(a.size());
	S4_Simulation *copy = S4_Simulation_Clone(s);
	int error = S4_Simulation_GetFieldCoefficientsMany(s, 3, z, a.data());
	if(!error){ error = S4_Simulation_GetFieldCoefficientsMany(copy, 3, z, b.data()); }
	S4_Simulation_Destroy(copy);
	if(error){ return error; }
	for(size_t i = 0; i < a.size(); ++i){
		if(!std::isfinite(a[i]) || std::abs(a[i]-b[i]) > 2e-11*(1+std::abs(b[i]))){ return 99; }
	}
	return 0;
}

int main(){
	double lattice[] = {1,0,.1,.9}, vacuum[] = {1,0}, film[] = {7.1,.1};
	S4_Simulation *s = S4_Simulation_New(lattice, 32, NULL);
	int air = S4_Simulation_SetMaterial(s, -1, "air", S4_MATERIAL_TYPE_SCALAR_COMPLEX, vacuum);
	int medium = S4_Simulation_SetMaterial(s, -1, "film", S4_MATERIAL_TYPE_SCALAR_COMPLEX, film);
	double zero = 0., thick = .2;
	S4_Simulation_SetLayer(s, -1, "top", &zero, -1, air);
	int layer = S4_Simulation_SetLayer(s, -1, "film", &thick, -1, medium);
	S4_Simulation_SetLayer(s, -1, "bottom", &zero, -1, air);
	double halfwidth[] = {.19,.19}, center[] = {.03,-.04};
	S4_Layer_SetRegionHalfwidths(s, layer, air, S4_REGION_TYPE_CIRCLE, halfwidth, center, NULL);
	double angles[] = {.2,.3}, ps[] = {.3,0}, pp[] = {1,0}, frequency[] = {.91,0};
	Simulation_MakeExcitationPlanewave(s, angles, ps, pp, 0);
	S4_Simulation_SetFrequency(s, frequency);
	if(compare_clone(s)){ return 1; }
	frequency[0] = .92;
	S4_Simulation_SetFrequency(s, frequency);
	if(compare_clone(s) || !s->epsilon_cache_hits){ return 2; }
	S4_Simulation_SetBases(s, 64, NULL);
	if(s->epsilon_cache_bytes || compare_clone(s)){ return 3; }
	lattice[2] = .23; lattice[3] = .87;
	S4_Simulation_SetLattice(s, lattice);
	if(s->epsilon_cache_bytes || compare_clone(s)){ return 4; }
	Simulation_SetNumG(s, 32);
	if(s->epsilon_cache_bytes || compare_clone(s)){ return 5; }
	S4_Layer_ClearRegions(s, layer);
	if(s->epsilon_cache_bytes || compare_clone(s)){ return 6; }
	S4_Simulation_Destroy(s);
	puts("Native field cache basis/lattice/clear-region tests passed");
	return 0;
}
