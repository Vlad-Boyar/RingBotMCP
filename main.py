from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

@app.get("/")
async def root():
    return {"status": "alive"}

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    print("👉 Received:", data)

    if data.get("method") == "initialize":
        response = {
            'jsonrpc': '2.0',
            'id': 0,
            'result': {
                'protocolVersion': '2025-03-26',
                'capabilities': {
                'customTools': [
                    {
                    'name': 'DemoToolUniqueXYZ',
                    'description': 'A simple test tool',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                        'foo': {
                            'type': 'string',
                            'description': 'Foo bar'
                        }
                        },
                        'required': ['foo']
                    }
                    }
                ],
                'supportsRecording': False
                }
            }
            }

        print("✅ Sending initialize response:", response)
        return JSONResponse(response)

    elif data.get("method") == "tools/DemoTool":
        foo = data.get("params", {}).get("foo")
        print(f"✅ Tool call: foo = {foo}")
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": data.get("id"),
            "result": {
                "status": "success",
                "echo": foo
            }
        })

    else:
        print("⚠️ Unrecognized:", data)

    return JSONResponse({"status": "ok"})
