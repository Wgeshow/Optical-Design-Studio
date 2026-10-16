"""Representative finite-volume cell using the shared editable transport model.

The recovered raster study used insulating lateral faces, not periodic wrap
edges. This adapter preserves that distinction beside periodic conformal FE.
"""
import copy
from advanced_transport import FIELD_SCHEMA
from input_diagnostics import InputValidationError

CAPABILITIES=dict(label='Representative PCSEL cell transport',dimensions=[3],optional_runtime='DEVSIM',
    limitations=['The current editable finite device is a representative cell with insulating lateral faces; no periodic current wrap.',
        'Raster geometry and full conservative face currents; no claim of a boundary-fitted mesh.',
        'Semiconductor parameters, dopants, ideal interfaces and optional recombination remain explicit user inputs; optical index does not determine electrical composition.'])
FIELD_SCHEMA=copy.deepcopy(FIELD_SCHEMA)


def prepare(project,settings):
    import advanced_transport
    try:return advanced_transport.prepare(project,settings)
    except InputValidationError as exc:
        rows=copy.deepcopy(exc.diagnostics)
        for row in rows:row.update(workspace='research_studies',model_id='pcsel_unitcell_transport')
        raise InputValidationError(rows) from exc


def execute(prepared,directory,emit=lambda event:None,cancelled=lambda:False):
    import advanced_transport
    result=advanced_transport.execute(prepared,directory,emit,cancelled)
    result=copy.deepcopy(result)
    result.update(engine='pcsel_unitcell_transport',model_scope='representative_cell_insulating_lateral_faces')
    result.setdefault('limitations',[]).extend(CAPABILITIES['limitations'])
    return result
