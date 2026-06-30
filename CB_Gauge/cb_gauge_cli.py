import asyncio
import json
import argparse
from pathlib import Path
from mcp import ClientSession
from mcp.client.sse import sse_client

async def test_file(input_path: Path, server_url: str):
    if not input_path.exists():
        print(f"❌ Error: File not found: {input_path}")
        return

    output_dir = input_path.parent / "cb_test_results"
    output_dir.mkdir(exist_ok=True)
    out_path = output_dir / f"results_{input_path.name}"

    print(f"\n--- Loading {input_path.name} ---")
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            questions = json.load(f)
    except Exception as e:
        print(f"❌ Error reading JSON: {e}")
        return

    if not isinstance(questions, list):
        print(f"❌ Error: Expected a JSON array of questions, but got {type(questions).__name__}")
        return

    print(f"Found {len(questions)} questions. Connecting to Context Bridge at {server_url} ...")

    try:
        async with sse_client(server_url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                print("✅ Session initialized successfully.\n")
                
                results = []
                for i, q in enumerate(questions, 1):
                    q_id = q.get("id", f"Q_UNKNOWN_{i}")
                    query = q.get("question")
                    
                    if not query:
                        print(f"⚠️ Skipping {q_id}: No 'question' field found.")
                        continue
                        
                    print(f"Processed {q_id} ({i}/{len(questions)})... ", end="", flush=True)
                    
                    try:
                        # Use wait_for to prevent hanging if Context Bridge gets stuck
                        result = await asyncio.wait_for(
                            session.call_tool("search_context_hybrid", arguments={"query": query}),
                            timeout=240.0
                        )
                        
                        # Convert tool results to JSON serializable format
                        content = []
                        if result and hasattr(result, 'content'):
                            for c in result.content:
                                if hasattr(c, 'model_dump'):
                                    content.append(c.model_dump())
                                elif hasattr(c, '__dict__'):
                                    content.append(c.__dict__)
                                else:
                                    content.append(str(c))
                        else:
                            content = str(result)
                            
                        results.append({
                            "id": q_id,
                            "question": query,
                            "result": content,
                            "error": None
                        })
                        print("✅ Success!")
                    except asyncio.TimeoutError:
                        print("❌ Timeout!")
                        results.append({"id": q_id, "question": query, "result": None, "error": "Timeout after 240s"})
                    except Exception as e:
                        print(f"❌ Error: {e}")
                        results.append({"id": q_id, "question": query, "result": None, "error": str(e)})
                        
                # Save the results
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(results, f, indent=2, ensure_ascii=False)
                print(f"\n🎉 Finished! Saved results to: {out_path}\n")
                
    except Exception as e:
        print(f"\n❌ Failed to connect to Context Bridge or run test: {e}")
        print("Please ensure Context Bridge is running before executing this script.")

def main():
    parser = argparse.ArgumentParser(description="Context Bridge Batch Tester Tool")
    parser.add_argument("files", nargs="+", help="One or more JSON files containing the test questions")
    parser.add_argument("--url", default="http://127.0.0.1:8755/sse", help="The Context Bridge SSE Server URL")
    
    args = parser.parse_args()
    
    for file_path in args.files:
        path = Path(file_path).resolve()
        asyncio.run(test_file(path, args.url))

if __name__ == "__main__":
    main()
