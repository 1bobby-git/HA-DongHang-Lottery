/**
 * 동행복권 릴레이 - Cloudflare Worker
 *
 * HA 서버에서 동행복권 사이트에 직접 접속이 안 되는 경우
 * 이 Worker를 배포하여 릴레이로 사용합니다.
 *
 * 배포 방법:
 * 1. https://dash.cloudflare.com/ 에서 무료 계정 생성
 * 2. Workers & Pages → Create Worker
 * 3. 이 코드를 붙여넣고 Deploy
 * 4. 생성된 URL (예: https://dh-relay.your-id.workers.dev)을
 *    HA 동행복권 통합 설정의 "릴레이 서버 URL"에 입력
 *
 * URL 매핑:
 *   /path       → https://www.dhlottery.co.kr/path
 *   /ol/path    → https://ol.dhlottery.co.kr/path
 *   /el/path    → https://el.dhlottery.co.kr/path
 */

const TARGET_HOSTS = {
  default: 'www.dhlottery.co.kr',
  ol: 'ol.dhlottery.co.kr',
  el: 'el.dhlottery.co.kr',
};

export default {
  async fetch(request) {
    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
          'Access-Control-Allow-Headers': '*',
          'Access-Control-Max-Age': '86400',
        },
      });
    }

    const url = new URL(request.url);
    let targetHost = TARGET_HOSTS.default;
    let targetPath = url.pathname;

    // /ol/... → ol.dhlottery.co.kr/...
    if (targetPath.startsWith('/ol/')) {
      targetHost = TARGET_HOSTS.ol;
      targetPath = targetPath.slice(3); // Remove '/ol'
    }
    // /el/... → el.dhlottery.co.kr/...
    else if (targetPath.startsWith('/el/')) {
      targetHost = TARGET_HOSTS.el;
      targetPath = targetPath.slice(3); // Remove '/el'
    }

    const targetUrl = `https://${targetHost}${targetPath}${url.search}`;

    // Forward headers (remove hop-by-hop headers)
    const headers = new Headers(request.headers);
    headers.set('Host', targetHost);
    headers.set('Origin', `https://${targetHost}`);

    // Rewrite Referer to target host
    const referer = headers.get('Referer');
    if (referer) {
      try {
        const refUrl = new URL(referer);
        refUrl.hostname = targetHost;
        refUrl.protocol = 'https:';
        // Fix path prefix for subdomains
        if (targetHost !== TARGET_HOSTS.default) {
          const prefix = Object.entries(TARGET_HOSTS)
            .find(([, v]) => v === targetHost)?.[0];
          if (prefix && refUrl.pathname.startsWith(`/${prefix}/`)) {
            refUrl.pathname = refUrl.pathname.slice(prefix.length + 1);
          }
        }
        headers.set('Referer', refUrl.toString());
      } catch {
        headers.delete('Referer');
      }
    }

    // Remove headers that might cause issues
    headers.delete('cf-connecting-ip');
    headers.delete('cf-ipcountry');
    headers.delete('cf-ray');
    headers.delete('cf-visitor');
    headers.delete('x-forwarded-for');
    headers.delete('x-forwarded-proto');
    headers.delete('x-real-ip');

    try {
      const response = await fetch(targetUrl, {
        method: request.method,
        headers: headers,
        body: request.body,
        redirect: 'manual',
      });

      // Build response headers
      const responseHeaders = new Headers();

      // Copy response headers
      for (const [key, value] of response.headers.entries()) {
        const lowerKey = key.toLowerCase();
        // Skip hop-by-hop and security headers that might conflict
        if (['transfer-encoding', 'connection', 'keep-alive'].includes(lowerKey)) {
          continue;
        }
        // Rewrite Set-Cookie domain
        if (lowerKey === 'set-cookie') {
          const rewritten = value
            .replace(/domain=[^;]*/gi, '')
            .replace(/secure;?/gi, '')
            .replace(/samesite=[^;]*/gi, 'SameSite=None');
          responseHeaders.append(key, rewritten);
        }
        // Rewrite Location header for redirects
        else if (lowerKey === 'location') {
          let location = value;
          for (const [prefix, host] of Object.entries(TARGET_HOSTS)) {
            location = location.replace(
              `https://${host}`,
              prefix === 'default' ? url.origin : `${url.origin}/${prefix}`
            );
          }
          responseHeaders.set(key, location);
        } else {
          responseHeaders.set(key, value);
        }
      }

      // CORS headers
      responseHeaders.set('Access-Control-Allow-Origin', '*');
      responseHeaders.set('Access-Control-Expose-Headers', '*');

      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: responseHeaders,
      });
    } catch (err) {
      return new Response(JSON.stringify({ error: err.message }), {
        status: 502,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
        },
      });
    }
  },
};
