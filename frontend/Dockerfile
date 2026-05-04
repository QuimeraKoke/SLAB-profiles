FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Build the production bundle. `NEXT_PUBLIC_*` env vars are baked in at
# build time, so the platform (Railway) must pass them as build args /
# build-time env vars BEFORE this step runs.
RUN npm run build

EXPOSE 3000

# Production server. Local docker-compose overrides this with
# `command: npm run dev` to keep hot-reload during development.
CMD ["npm", "run", "start"]
