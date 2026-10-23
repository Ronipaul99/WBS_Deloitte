FROM node:22-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL
ARG VITE_PASSWORD_RECOVERY_ENABLED=false
ARG VITE_AUTH_MODE=local
ARG VITE_SSO_ENABLED=false
ARG VITE_SSO_PROVIDER_LABEL=Enterprise SSO
ENV VITE_API_URL=${VITE_API_URL} \
    VITE_PASSWORD_RECOVERY_ENABLED=${VITE_PASSWORD_RECOVERY_ENABLED} \
    VITE_AUTH_MODE=${VITE_AUTH_MODE} \
    VITE_SSO_ENABLED=${VITE_SSO_ENABLED} \
    VITE_SSO_PROVIDER_LABEL=${VITE_SSO_PROVIDER_LABEL}
RUN if ! printf '%s' "$VITE_API_URL" | \
    grep -Eq '^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?/api/v1$'; then \
    echo "VITE_API_URL must be an HTTPS /api/v1 URL" >&2; exit 1; fi && \
    if ! printf '%s' "$VITE_AUTH_MODE" | grep -Eq '^(local|oidc|hybrid)$'; then \
    echo "VITE_AUTH_MODE must be local, oidc, or hybrid" >&2; exit 1; fi && npm run build

FROM nginx:1.27-alpine AS runtime

ENV API_ORIGIN=https://api.example.invalid
COPY nginx.conf /etc/nginx/nginx.conf
COPY nginx.default.conf.template /etc/nginx/templates/default.conf.template
COPY docker-entrypoint.d/05-validate-public-origin.sh /docker-entrypoint.d/05-validate-public-origin.sh
COPY --from=builder /app/dist /usr/share/nginx/html
RUN rm -f /etc/nginx/conf.d/default.conf && \
    mkdir -p /var/cache/nginx/client_temp /var/cache/nginx/proxy_temp && \
    chmod 0555 /docker-entrypoint.d/05-validate-public-origin.sh && \
    chown -R nginx:nginx /etc/nginx/conf.d /var/cache/nginx /usr/share/nginx/html

USER nginx
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["wget", "--quiet", "--tries=1", "--spider", "http://127.0.0.1:8080/"]
