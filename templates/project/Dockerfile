FROM node:22-alpine AS runtime
WORKDIR /app
ARG APP_VERSION=development
ENV NODE_ENV=production PORT=8080 APP_VERSION=$APP_VERSION
COPY --chown=node:node package.json ./
COPY --chown=node:node src ./src
COPY --chown=node:node --chmod=755 bin/healthcheck ./bin/healthcheck
USER node
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=12 CMD ["/app/bin/healthcheck"]
CMD ["node", "src/server.js"]

FROM postgres:16-alpine AS migrate
RUN apk add --no-cache python3
WORKDIR /app
COPY --chown=postgres:postgres sql ./sql
COPY --chown=postgres:postgres --chmod=755 bin/migrate bin/bootstrap bin/db.py ./bin/
USER postgres
ENTRYPOINT []
CMD ["/app/bin/migrate"]
