"""Live geometry preview of the committed project; no simulation is required."""
import gradio as gr

from structure_preview import build_structure_figure


def build_structure_preview(layers, patterns, selected_layer, ax, ay, initial_layers, initial_patterns, initial_selected):
    with gr.Accordion('Structure preview · top and side views', open=True):
        gr.Markdown('See the applied geometry: the top view shows the selected layer; the side view cuts through the whole stack. Colors identify materials. Use **Apply layer** or **Apply region** to update the geometry, then zoom or hover for detail.')
        with gr.Row():
            cells = gr.Dropdown([('One unit cell',1),('3 × 3 unit cells',3),('5 × 5 unit cells',5)],
                                value=3,label='Periodic cells to display',allow_custom_value=False)
            cut_y = gr.Number(0,label='Side-view Y position (µm)',
                              info='The dashed line in the top view marks this cross-section.')
        plot = gr.Plot(value=build_structure_figure(initial_layers,initial_patterns,initial_selected,ax.value,ay.value,3,0),
                       label='Structure geometry',show_label=False)
        inputs=[layers,patterns,selected_layer,ax,ay,cells,cut_y]
        gr.on([layers.change,patterns.change,selected_layer.change,ax.change,ay.change,cells.change,cut_y.change],
              build_structure_figure,inputs,plot,api_name='preview_structure',preprocess=False,
              trigger_mode='always_last',concurrency_id='structure_preview',concurrency_limit=1,
              queue=True,show_progress='hidden')
    return dict(plot=plot,cells=cells,cut_y=cut_y)
