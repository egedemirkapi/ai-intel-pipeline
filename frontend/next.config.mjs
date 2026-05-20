/** @type {import('next').NextConfig} */
const nextConfig = {
  // The dashboard is a pure client of the Jarvis Brain API; no server
  // actions or DB access from Next itself.
  reactStrictMode: true,
};

export default nextConfig;
