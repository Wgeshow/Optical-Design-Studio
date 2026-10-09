import unittest
from unittest.mock import patch
import ioffe_parameters as ip

class IoffeTests(unittest.TestCase):
    def setUp(self):ip._CACHE.clear()

    def test_numeric_cached_data_and_provenance(self):
        si=ip.material_parameters('Si')
        self.assertEqual(si['values']['relative_permittivity'],11.7)
        self.assertEqual(si['values']['intrinsic_cm3'],1e10)
        self.assertIn('doi.org',si['field_sources']['mass_h_m0'])
        gaas=ip.material_parameters('GaAs')
        self.assertEqual(gaas['values']['mass_e_m0'],.063)
        self.assertNotIn('mass_h_m0',gaas['values'])
        self.assertIn('mass_h_m0',gaas['missing'])
        self.assertIn('upper bounds',' '.join(gaas['notes']))

    def test_alloy_formula_domains_and_no_dos_substitution(self):
        direct=ip.material_parameters('AlGaAs',.3)
        self.assertAlmostEqual(direct['values']['mass_e_m0'],.0879)
        self.assertAlmostEqual(direct['values']['relative_permittivity'],12.048)
        self.assertAlmostEqual(direct['values']['mobility_e_cm2_Vs'],2300)
        self.assertEqual(direct['values']['intrinsic_cm3'],2100)
        indirect=ip.material_parameters('AlGaAs',.5)
        self.assertEqual(indirect['values']['mass_e_m0'],.26)
        self.assertNotEqual(indirect['values']['mass_e_m0'],.85-.14*.5)
        crossing=ip.material_parameters('AlGaAs',.45)
        self.assertNotIn('mass_e_m0',crossing['values'])
        self.assertNotIn('mobility_e_cm2_Vs',crossing['values'])
        self.assertNotIn('intrinsic_cm3',ip.material_parameters('AlGaAs',.2)['values'])
        for x in (-.1,1.1,float('nan'),True,None):
            with self.assertRaises(ValueError):ip.material_parameters('AlGaAs',x)

    def test_parse_realistic_html_scientific_and_formula(self):
        html='''<table><tr><td>Dielectric constant (static)</td><td>12.90-2.84x</td></tr>
        <tr><td>Effective electron mass m<sub>e</sub></td><td>0.063+0.083x m<sub>o</sub> (x&lt;0.45)</td></tr>
        <tr><td>Density-of-states electron mass</td><td>0.85-0.14x</td></tr>
        <tr><td>Effective hole masses m<sub>h</sub></td><td>0.51+0.25x</td></tr></table>'''
        values=ip.parse_page(html,'AlGaAs',.3)
        self.assertAlmostEqual(values['mass_e_m0'],.0879)
        self.assertAlmostEqual(values['heavy_hole_mass_m0'],.585)
        self.assertNotIn('mass_h_m0',values)
        html='<table><tr><td>Intrinsic carrier concentration</td><td>2.1&middot;10<sup>6</sup> cm<sup>-3</sup></td></tr></table>'
        self.assertEqual(ip.parse_page(html,'GaAs')['intrinsic_cm3'],2.1e6)

    def test_remote_text_never_executed_and_fallback(self):
        with self.assertRaises(ValueError):ip._number('__import__("os").system("echo bad")')
        with patch.object(ip,'_fetch',side_effect=OSError('offline')):
            data=ip.material_parameters('GaAs',refresh=True)
        self.assertEqual(data['status'],'bundled-cache')
        self.assertIsNone(data['fetched_at'])
        self.assertEqual(data['values']['relative_permittivity'],12.9)

    def test_live_fetch_parses_instead_of_only_checking_availability(self):
        html='<table><tr><td>Dielectric constant (static)</td><td>12.85</td></tr></table>'
        with patch.object(ip,'_fetch',return_value=html):data=ip.material_parameters('GaAs',refresh=True)
        self.assertEqual(data['status'],'mixed')
        self.assertEqual(data['values']['relative_permittivity'],12.85)
        self.assertIsNotNone(data['fetched_at'])
        data['values']['relative_permittivity']=0
        self.assertEqual(ip.material_parameters('GaAs')['values']['relative_permittivity'],12.85)

if __name__=='__main__':unittest.main()
