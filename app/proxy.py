import httpx
from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from .services_manager import services_manager

# Blacklisted hop-by-hop headers
HOP_BY_HOP = {
    'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
    'te', 'trailers', 'transfer-encoding', 'upgrade', 'content-length'
}

async def proxy_service_request(service_id: str, path: str, request: Request) -> Response:
    status_info = await services_manager.get_service_status(service_id)
    if not status_info or status_info.get("status") != "RUNNING":
        return Response(content=f"Service '{service_id}' is not running.", status_code=503)

    port = status_info.get("port")
    if not port:
        return Response(content=f"Service '{service_id}' has no defined port.", status_code=400)

    target_url = f"http://127.0.0.1:{port}/{path.lstrip('/')}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    # Filter incoming headers
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP and k.lower() != 'host'
    }
    headers['host'] = f"127.0.0.1:{port}"

    body = await request.body()

    client = httpx.AsyncClient(timeout=60.0)
    try:
        req = client.build_request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body
        )
        resp = await client.send(req, stream=True)

        # Build response headers
        resp_headers = {}
        for k, v in resp.headers.items():
            k_lower = k.lower()
            if k_lower in HOP_BY_HOP:
                continue
            # Remove framing blockers so it can render inside our unified workspace iframe
            if k_lower in ['x-frame-options', 'content-security-policy']:
                continue
            resp_headers[k] = v

        resp_headers["X-Frame-Options"] = "ALLOWALL"

        async def stream_content():
            async for chunk in resp.aiter_bytes():
                yield chunk
            await client.aclose()

        return StreamingResponse(
            stream_content(),
            status_code=resp.status_code,
            headers=resp_headers,
            media_type=resp.headers.get("content-type")
        )
    except Exception as e:
        await client.aclose()
        return Response(content=f"Proxy error connecting to {target_url}: {str(e)}", status_code=502)
