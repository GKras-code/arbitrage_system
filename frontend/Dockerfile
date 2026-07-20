# ---- Стадия сборки ----
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json ./
RUN npm ci

COPY . ./
RUN npm run build

# ---- Стадия раздачи (nginx) ----
FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
