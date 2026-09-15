"""Plain-language GPU diagnostics shared by the GUI and isolated workers."""
from model import MODES


def gpu_requested(perf):
    return perf.get('mode', MODES[0]) != MODES[0]


def acceleration_warnings(info, perf):
    if not gpu_requested(perf):
        return []
    status = ' '.join(str(value) for value in info.get('statuses', {}).values())
    if 'no CUDA support' in status:
        return ['This S4 extension was built without CUDA support. On Linux rebuild with '
                'bash setup_linux.sh --cuda and a compatible CUDA toolkit.']
    if info.get('gpu_failures', 0):
        return ['GPU execution failed and S4 used CPU fallback. Check the selected CUDA device '
                'and compatible cuBLAS runtime with Check selected runtime. Native status: '+status]
    if not info.get('gpu_gemm_calls', 0):
        return [f"No GPU matrix products completed at the selected minimum matrix size {perf['gpu_min_n']}. "
                'Small or uniform structures can remain on CPU. Check selected runtime tests the GPU '
                'with a threshold of 1; Use GPU for small matrices also applies that threshold to future runs.']
    return []


def acceleration_summary(info):
    return (f"CPU matrix products: {info.get('cpu_gemm_calls', 0):,}; "
            f"GPU matrix products: {info.get('gpu_gemm_calls', 0):,}; "
            f"GPU failures: {info.get('gpu_failures', 0):,}.")


def gpu_settings_note(mode, threshold, basis):
    if mode == MODES[0]:
        return 'CPU mode is selected. Choose a GPU compute mode to enable eligible S4 matrix products.'
    if threshold is None or basis is None:
        return 'Enter a Fourier basis and minimum GPU matrix size to see the current offload settings.'
    return (f'Your Fourier basis is **{basis:g}** and the GPU threshold is **{threshold:g}**. '
            'A matrix product reaches the GPU only when all three of its dimensions meet the threshold. '
            'The default threshold of 1024 can leave small structures entirely on CPU. '
            'Use GPU for small matrices sets the threshold to 1; it can be slower for small problems. '
            'Check selected runtime verifies an actual GPU product separately from this threshold.')


def runtime_check_summary(info, selected_perf):
    if not gpu_requested(selected_perf):
        return '**CPU runtime check completed.** Select a GPU compute mode to test the GPU.\n\n'+acceleration_summary(info)
    if info.get('gpu_gemm_calls', 0) > 0 and not info.get('gpu_failures', 0):
        result = f"**GPU connection verified on CUDA device {selected_perf['gpu_device']}.**"
    else:
        result = '**GPU check failed: no successful, failure-free GPU execution was verified.**'
    result += ('\n\n'+acceleration_summary(info)+
               f" The diagnostic used a minimum matrix size of 1. Your run threshold remains {selected_perf['gpu_min_n']}.")
    for warning in info.get('warnings', []):
        result += '\n\n'+warning
    return result
