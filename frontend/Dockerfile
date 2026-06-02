FROM node:22-alpine

WORKDIR /app

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./

ARG NEXT_PUBLIC_FISORA_API_BASE_URL=/api
ENV NEXT_PUBLIC_FISORA_API_BASE_URL=${NEXT_PUBLIC_FISORA_API_BASE_URL}

RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "start"]
