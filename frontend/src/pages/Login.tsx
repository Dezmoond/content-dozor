import { useState } from 'react'
import { Alert, Button, Card, PasswordInput, Stack, Tabs, Text, TextInput, Title } from '@mantine/core'
import { useAuth } from '../auth/AuthContext'

export default function Login() {
  const { login, register } = useAuth()
  const [email, setEmail] = useState('admin@diplom.local')
  const [password, setPassword] = useState('123456')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState<string | null>('login')

  const onSubmit = async () => {
    setLoading(true)
    setError('')
    try {
      if (tab === 'register') {
        await register(email.trim(), password)
      } else {
        await login(email.trim(), password)
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка входа')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Stack maw={420} mx="auto" mt={80} gap="lg">
      <div>
        <Title order={2}>Контент Дозор</Title>
        <Text c="dimmed" size="sm" mt={4}>Вход в систему анализа документов</Text>
      </div>
      <Card withBorder padding="lg" style={{ background: '#161B22', borderColor: '#30363D' }}>
        <Tabs value={tab} onChange={setTab}>
          <Tabs.List mb="md">
            <Tabs.Tab value="login">Вход</Tabs.Tab>
            <Tabs.Tab value="register">Регистрация</Tabs.Tab>
          </Tabs.List>
          <Stack>
            <TextInput label="Email" value={email} onChange={(e) => setEmail(e.currentTarget.value)} />
            <PasswordInput label="Пароль" value={password} onChange={(e) => setPassword(e.currentTarget.value)} />
            {error && <Alert color="red">{error}</Alert>}
            <Button onClick={onSubmit} loading={loading}>
              {tab === 'register' ? 'Зарегистрироваться' : 'Войти'}
            </Button>
          </Stack>
        </Tabs>
      </Card>
      <Alert color="gray" variant="light">
        Демо: <b>admin@diplom.local</b> / <b>user@diplom.local</b>, пароль <b>123456</b>
      </Alert>
    </Stack>
  )
}
