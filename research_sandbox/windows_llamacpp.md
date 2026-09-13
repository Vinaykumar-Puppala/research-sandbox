Stop-Process -Name "python" -Force -ErrorAction SilentlyContinue
Stop-Process -Name "uvicorn" -Force -ErrorAction SilentlyContinue
Stop-Process -Name "fastapi" -Force -ErrorAction SilentlyContinue
Remove-Item "C:\Python311\Scripts\*.deleteme" -Force -ErrorAction SilentlyContinue

set FORCE_CMAKE=1
set CMAKE_ARGS=-DGGML_CUDA=on
pip install llama-cpp-python[server] --no-cache-dir

python -m llama_cpp.server --model "C:\Models\Llama-3.2-3B-Instruct-Q4_K_M.gguf" --host 0.0.0.0 --port 8000 --n_ctx 2048 --n_gpu_layers 30
python -m llama_cpp.server --model "C:\Models\Llama-3.2-3B-Instruct-Q4_K_M.gguf" --host 0.0.0.0 --port 8000 --n_gpu_layers 32 --n_ctx 2048
python -m llama_cpp.server --model qwen2.5-1.5b-instruct-q8_0.gguf --host 0.0.0.0 --port 8000 --n_gpu_layers 35 --n_ctx 4096


# Qwen/Qwen2.5-1.5B-Instruct-GGUF
--n_gpu_layers 35: The Qwen 1.5B model has 28 total layers. --n_ctx 4096:  
 --n_ctx 2048
--n_gpu_layers 32