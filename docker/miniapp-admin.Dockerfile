FROM node:20-alpine AS build
WORKDIR /app
COPY miniapps/admin/package*.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm install
COPY miniapps/admin .
COPY miniapps/shared /miniapp-shared
RUN ln -s /app/node_modules /miniapp-shared/node_modules && \
    npx vite build --outDir dist

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY miniapps/admin/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
