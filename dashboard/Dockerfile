FROM node:20-alpine AS build
WORKDIR /app/dashboard
COPY dashboard/package*.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm install
COPY dashboard ./
COPY shared ../shared
RUN npx vite build --outDir dist

FROM nginx:alpine
COPY --from=build /app/dashboard/dist /usr/share/nginx/html
COPY dashboard/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
