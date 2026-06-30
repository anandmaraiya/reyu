FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
# Drop the lockfile if it was generated on a different platform (Windows
# vs Linux) — Rollup's native binaries are pinned by OS in optionalDeps,
# so a Windows-generated lockfile fails npm install on Linux with
# EBADPLATFORM. We let npm regenerate it cleanly inside the container.
RUN rm -f package-lock.json && npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
