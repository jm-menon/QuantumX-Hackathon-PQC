FROM node:22-alpine AS build

WORKDIR /app
ARG VITE_P1_URL=http://localhost:8001
ARG VITE_P2_URL=http://localhost:8002
ENV VITE_P1_URL=${VITE_P1_URL} \
    VITE_P2_URL=${VITE_P2_URL}

COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
