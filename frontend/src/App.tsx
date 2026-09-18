import { useState } from 'react'
import { BrowserRouter, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import {
  AppShell, Burger, Group, Text, NavLink as MNavLink, ScrollArea, Badge, Stack, Button, Loader, Center,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import {
  IconDashboard, IconBriefcase, IconHistory, IconCpu,
  IconAdjustments, IconDatabase, IconFileText, IconSettings, IconBan, IconLogout,
} from '@tabler/icons-react'
import { AuthProvider, useAuth } from './auth/AuthContext'
import Dashboard from './pages/Dashboard'
import Cases from './pages/Cases'
import CaseDetail from './pages/CaseDetail'
import History from './pages/History'
import Models from './pages/Models'
import Methods from './pages/Methods'
import Sources from './pages/Sources'
import Logs from './pages/Logs'
import Settings from './pages/Settings'
import ForbiddenLexicon from './pages/ForbiddenLexicon'
import Login from './pages/Login'

const links = [
  { to: '/', label: 'Dashboard', icon: IconDashboard, adminOnly: false },
  { to: '/cases', label: 'Кейсы', icon: IconBriefcase, adminOnly: false },
  { to: '/history', label: 'История', icon: IconHistory, adminOnly: false },
  { to: '/models', label: 'Модели', icon: IconCpu, adminOnly: true },
  { to: '/methods', label: 'Методы', icon: IconAdjustments, adminOnly: true },
  { to: '/forbidden-lexicon', label: 'Запретный лексикон', icon: IconBan, adminOnly: true },
  { to: '/sources', label: 'Источники', icon: IconDatabase, adminOnly: true },
  { to: '/logs', label: 'Логи', icon: IconFileText, adminOnly: true },
  { to: '/settings', label: 'Настройки', icon: IconSettings, adminOnly: false },
]

function Shell() {
  const [opened, { toggle }] = useDisclosure()
  const { user, loading, isAdmin, logout } = useAuth()

  if (loading) {
    return (
      <Center h="100vh" style={{ background: '#0F1419' }}>
        <Loader />
      </Center>
    )
  }

  if (!user) {
    return <Login />
  }

  const visibleLinks = links.filter((l) => !l.adminOnly || isAdmin)

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 260, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="md"
      styles={{ main: { background: '#0F1419' }, header: { background: '#161B22', borderBottom: '1px solid #30363D' }, navbar: { background: '#161B22', borderRight: '1px solid #30363D' } }}
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group>
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Text fw={700} size="lg" c="blue.3">Контент Дозор</Text>
            <Badge variant="light" color="gray">DIPLOM</Badge>
          </Group>
          <Group gap="md">
            <Text size="sm" c="dimmed">{user.email}</Text>
            <Badge size="sm" color={isAdmin ? 'violet' : 'teal'}>{user.role}</Badge>
            <Button size="xs" variant="light" leftSection={<IconLogout size={14} />} onClick={logout}>
              Выйти
            </Button>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="md">
        <ScrollArea>
          <Stack gap={4}>
            {visibleLinks.map((l) => (
              <MNavLink
                key={l.to}
                component={NavLink}
                to={l.to}
                end={l.to === '/'}
                label={l.label}
                leftSection={<l.icon size={18} stroke={1.5} />}
                styles={{ root: { borderRadius: 8 } }}
              />
            ))}
          </Stack>
        </ScrollArea>
      </AppShell.Navbar>
      <AppShell.Main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/cases" element={<Cases />} />
          <Route path="/cases/:caseId" element={<CaseDetail />} />
          <Route path="/documents" element={<Navigate to="/cases" replace />} />
          <Route path="/history" element={<History />} />
          {isAdmin && (
            <>
              <Route path="/models" element={<Models />} />
              <Route path="/methods" element={<Methods />} />
              <Route path="/forbidden-lexicon" element={<ForbiddenLexicon />} />
              <Route path="/sources" element={<Sources />} />
              <Route path="/logs" element={<Logs />} />
            </>
          )}
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/cases" replace />} />
        </Routes>
      </AppShell.Main>
    </AppShell>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Shell />
      </AuthProvider>
    </BrowserRouter>
  )
}
