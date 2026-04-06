const CLOUD_RUN_HOST = "carnitrack-app-1000671720976.europe-west1.run.app";
export default {
  async fetch(request) {
    const url = new URL(request.url);
    const originalHost = url.hostname; // e.g. pomet.carnitrack.com

    // Rewrite to Cloud Run URL but keep original host in X-Forwarded-Host
    const targetUrl = new URL(request.url);
    targetUrl.hostname = CLOUD_RUN_HOST;
    targetUrl.protocol = "https:";

    const headers = new Headers(request.headers);
    // Cloud Run requires Host to match its .run.app domain
    headers.set("Host", CLOUD_RUN_HOST);
    // Django reads X-Forwarded-Host for tenant resolution (USE_X_FORWARDED_HOST=True)
    headers.set("X-Forwarded-Host", originalHost);
    headers.set("X-Forwarded-Proto", "https");

    return fetch(targetUrl.toString(), {
      method: request.method,
      headers,
      body: request.body,
      redirect: "manual",
    });
  },
};
