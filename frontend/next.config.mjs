/** @type {import('next').NextConfig} */
const nextConfig = {
  // 骨架阶段：暂不启用 ESLint 阻塞构建；业务开发期再补充 lint 配置。
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
