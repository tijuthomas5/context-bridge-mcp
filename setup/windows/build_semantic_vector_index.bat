@echo off
setlocal
:: Locate CB root dynamically — works regardless of where this script is placed
set "_S=%~dp0"
:_FIND_CB
if exist "%_S%mcp_server_hybrid.py" goto _CB_FOUND
for %%P in ("%_S%..") do set "_N=%%~fP\"
if /i "%_N%"=="%_S%" ( echo ERROR: Cannot find ContextBridge root & pause & exit /b 1 )
set "_S=%_N%" & goto _FIND_CB
:_CB_FOUND
set "CB_ROOT=%_S:~0,-1%"
for %%P in ("%CB_ROOT%\..") do set "ROOT=%%~fP"
cd /d "%ROOT%"
python context_bridge\rag\build_vector_index.py --config config.hybrid.json --backend sentence-transformers --model all-MiniLM-L6-v2 --chunks-output context_bridge\data\vector_chunks.semantic.jsonl --index-output context_bridge\data\vector_index.semantic.jsonl --manifest-output context_bridge\data\vector_meta.semantic.json --batch-size 32
