import React from 'react'
import ReactDOM from 'react-dom/client'
import { MantineProvider, createTheme } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@mantine/core/styles.css'
import App from './App'

const theme = createTheme({
  primaryColor: 'blue',
  fontFamily: 'Inter, system-ui, sans-serif',
  defaultRadius: 'md',
  colors: {
    dark: [
      '#C9D1D9', '#B1BAC4', '#8B949E', '#6E7681',
      '#484F58', '#30363D', '#21262D', '#161B22',
      '#0F1419', '#0B0E13',
    ],
  },
})

const queryClient = new QueryClient()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <MantineProvider theme={theme} defaultColorScheme="dark">
        <App />
      </MantineProvider>
    </QueryClientProvider>
  </React.StrictMode>,
)
