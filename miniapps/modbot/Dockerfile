FROM node:20-alpine AS build
WORKDIR /app
COPY apps/miniapp-modbot/package*.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm install
COPY apps/miniapp-modbot .
COPY packages /packages
RUN ln -s /app/node_modules /packages/node_modules && \
    npx vite build --outDir dist

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY apps/miniapp-modbot/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
