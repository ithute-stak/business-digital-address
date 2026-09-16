FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund

FROM node:22-alpine AS builder
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=/api/bda
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    BDA_RUNTIME_ENVIRONMENT=production \
    BDA_DEV_AUTH_BYPASS=false \
    BDA_APP_URL=https://business.ls \
    BDA_API_INTERNAL_URL=http://backend:8100 \
    BDA_ITHUTE_AUTH_URL=https://auth.ithute.co.ls \
    BDA_OIDC_CLIENT_ID=business-digital-address
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
