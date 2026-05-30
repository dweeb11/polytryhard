# syntax=docker/dockerfile:1

FROM node:24-alpine AS build
WORKDIR /app

ARG PUBLIC_BACKEND_URL
ARG PUBLIC_BACKEND_TOKEN
ENV PUBLIC_BACKEND_URL=$PUBLIC_BACKEND_URL
ENV PUBLIC_BACKEND_TOKEN=$PUBLIC_BACKEND_TOKEN

COPY ui/package*.json ui/.npmrc ./
RUN npm ci

COPY ui/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=5s --retries=10 CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
