FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# `NEXT_PUBLIC_*` values are inlined into the JS bundle at build time.
# Declare them as build args + re-export as ENV so `next build` sees them.
# Railway forwards service variables to the build by default, so setting
# NEXT_PUBLIC_API_URL on the frontend service's Variables tab is enough.
# Locally, docker-compose can pass `--build-arg NEXT_PUBLIC_API_URL=...`.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

# Build the production bundle.
RUN npm run build

EXPOSE 3000

# Production server. Local docker-compose overrides this with
# `command: npm run dev` to keep hot-reload during development.
CMD ["npm", "run", "start"]
