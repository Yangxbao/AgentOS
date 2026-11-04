import { QueryClient } from '@tanstack/react-query'

/**
 * 服务端状态配置：
 * - 本地单用户场景不需要激进重试；失败一次即可让用户看到错误
 * - staleTime 30s 避免组织图/列表频繁重复请求
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: 0,
    },
  },
})
