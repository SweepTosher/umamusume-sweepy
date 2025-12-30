import os
import sys
import time
import bot.base.log as logger

log = logger.get_logger(__name__)

_GPU_AVAILABLE = None
_GPU_DEVICE_COUNT = 0
_GPU_MEMORY_FRACTION = 0.3
_GPU_DEVICE_ID = 0
_LAST_GPU_CACHE_CLEAR = 0
_GPU_CACHE_CLEAR_INTERVAL = 11.0

def detect_gpu_capabilities():
    global _GPU_AVAILABLE, _GPU_DEVICE_COUNT
    
    if _GPU_AVAILABLE is not None:
        return _GPU_AVAILABLE
    
    try:
        import paddle
        
        if not paddle.device.is_compiled_with_cuda():
            log.warning("GPU acceleration disabled: PaddlePaddle not compiled with CUDA support")
            _GPU_AVAILABLE = False
            return False
        
        device_count = paddle.device.cuda.device_count()
        if device_count == 0:
            log.warning("GPU acceleration disabled: No CUDA devices detected (device_count=0)")
            _GPU_AVAILABLE = False
            return False
        
        _GPU_DEVICE_COUNT = device_count
        _GPU_AVAILABLE = True
        return True
        
    except ImportError as e:
        log.warning("GPU acceleration disabled: PaddlePaddle not installed")
        _GPU_AVAILABLE = False
        return False
    except Exception as e:
        log.warning(f"GPU acceleration disabled: {str(e)}")
        _GPU_AVAILABLE = False
        return False

def is_gpu_available():
    if _GPU_AVAILABLE is None:
        detect_gpu_capabilities()
    return _GPU_AVAILABLE

def get_gpu_device_count():
    if _GPU_AVAILABLE is None:
        detect_gpu_capabilities()
    return _GPU_DEVICE_COUNT

def set_gpu_config(memory_fraction=0.5, device_id=0):
    global _GPU_MEMORY_FRACTION, _GPU_DEVICE_ID
    _GPU_MEMORY_FRACTION = memory_fraction
    _GPU_DEVICE_ID = device_id

def get_gpu_memory_fraction():
    return _GPU_MEMORY_FRACTION

def get_gpu_device_id():
    return _GPU_DEVICE_ID

def configure_paddle_gpu():
    if not is_gpu_available():
        return
    
    try:
        import paddle
        paddle.device.set_device(f'gpu:{_GPU_DEVICE_ID}')
        
        os.environ['FLAGS_fraction_of_gpu_memory_to_use'] = str(_GPU_MEMORY_FRACTION)
        os.environ['FLAGS_allocator_strategy'] = 'auto_growth'
        os.environ['FLAGS_eager_delete_tensor_gb'] = '0'
        os.environ['FLAGS_memory_optimize_strategy'] = '1'
        os.environ['FLAGS_fast_eager_deletion_mode'] = 'true'
    except Exception as e:
        log.error(f"Failed to configure Paddle GPU: {e}")

def clear_gpu_cache():
    global _LAST_GPU_CACHE_CLEAR
    
    if not is_gpu_available():
        return
    
    current_time = time.time()
    if current_time - _LAST_GPU_CACHE_CLEAR < _GPU_CACHE_CLEAR_INTERVAL:
        return
    
    try:
        import paddle
        if hasattr(paddle.device, 'cuda') and hasattr(paddle.device.cuda, 'empty_cache'):
            paddle.device.cuda.empty_cache()
            _LAST_GPU_CACHE_CLEAR = current_time
    except Exception as e:
        log.debug(f"Failed to clear GPU cache: {e}")

def configure_opencv_gpu():
    try:
        import cv2
        if is_gpu_available():
            cv2.ocl.setUseOpenCL(True)
            if cv2.ocl.haveOpenCL():
                cv2.ocl.setUseOpenCL(True)
                return True
        cv2.ocl.setUseOpenCL(False)
        return False
    except Exception:
        return False