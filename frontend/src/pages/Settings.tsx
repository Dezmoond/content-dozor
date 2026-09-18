import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Group, NumberInput, PasswordInput, Radio, Stack, Text, TextInput,
} from '@mantine/core'
import { createDatabase, getSettings, putSetting, testDatabase } from '../api'
import { useAuth } from '../auth/AuthContext'

type DbConfig = {
  engine: string
  host: string
  port: number
  user: string
  password: string
  dbname: string
  password_set?: boolean
}

const DEFAULT_DB: DbConfig = {
  engine: 'sqlite',
  host: '127.0.0.1',
  port: 5432,
  user: 'postgres',
  password: '',
  dbname: 'content_dozor',
}

export default function SettingsPage() {
  const { isAdmin } = useAuth()
  const [ui, setUi] = useState({ theme: 'dark', analysis_panel_width: 720 })
  const [db, setDb] = useState<DbConfig>(DEFAULT_DB)
  const [saved, setSaved] = useState(false)
  const [msg, setMsg] = useState<{ color: string; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getSettings().then((s) => {
      if (s.ui) setUi(s.ui as typeof ui)
      if (s.database && typeof s.database === 'object') {
        const d = s.database as Partial<DbConfig>
        setDb({
          ...DEFAULT_DB,
          ...d,
          password: '',
          port: Number(d.port) || 5432,
        })
      }
    })
  }, [])

  const payload = () => ({
    engine: db.engine,
    host: db.host,
    port: db.port,
    user: db.user,
    password: db.password,
    dbname: db.dbname,
  })

  const save = async () => {
    setBusy(true)
    setMsg(null)
    try {
      await putSetting('database', payload())
      if (isAdmin) await putSetting('ui', ui)
      setSaved(true)
      setMsg({ color: 'green', text: 'Параметры сохранены' })
      setTimeout(() => setSaved(false), 2000)
    } catch (e: unknown) {
      setMsg({ color: 'red', text: e instanceof Error ? e.message : 'Ошибка сохранения' })
    } finally {
      setBusy(false)
    }
  }

  const onTest = async () => {
    setBusy(true)
    setMsg(null)
    try {
      const r = await testDatabase(payload())
      setMsg({ color: r.ok ? 'green' : 'red', text: r.message })
    } catch (e: unknown) {
      setMsg({ color: 'red', text: e instanceof Error ? e.message : 'Ошибка проверки' })
    } finally {
      setBusy(false)
    }
  }

  const onCreate = async () => {
    if (!isAdmin) return
    setBusy(true)
    setMsg(null)
    try {
      const r = await createDatabase({ ...payload(), init_schema: true })
      setMsg({
        color: 'green',
        text: `${r.message}${r.schema ? `. ${r.schema}` : ''}. Для работы платформы на PostgreSQL задайте DATABASE_URL и перезапустите сервисы.`,
      })
      setDb((prev) => ({ ...prev, password: '', password_set: true }))
    } catch (e: unknown) {
      setMsg({ color: 'red', text: e instanceof Error ? e.message : 'Не удалось создать базу' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Stack>
      <Text size="xl" fw={600}>Настройки</Text>
      <Card withBorder padding="lg" style={{ background: '#161B22', borderColor: '#30363D' }}>
        <Stack>
          <Text fw={600}>База данных</Text>
          <Text size="sm" c="dimmed">
            SQLite — локальный файл. PostgreSQL — укажите сервер, логин, пароль и имя базы.
            {isAdmin
              ? ' Администратор может создать новую базу на сервере.'
              : ' Обычный пользователь может только проверить и сохранить подключение к существующей базе.'}
          </Text>
          <Radio.Group
            value={db.engine}
            onChange={(v) => setDb((prev) => ({ ...prev, engine: v }))}
          >
            <Stack gap="xs" mt="xs">
              <Radio value="sqlite" label="SQLite (локально)" />
              <Radio value="postgresql" label="PostgreSQL" />
            </Stack>
          </Radio.Group>

          {db.engine === 'postgresql' && (
            <Stack gap="sm" mt="sm">
              <Group grow>
                <TextInput
                  label="Хост"
                  value={db.host}
                  onChange={(e) => setDb({ ...db, host: e.currentTarget.value })}
                />
                <NumberInput
                  label="Порт"
                  value={db.port}
                  min={1}
                  max={65535}
                  onChange={(v) => setDb({ ...db, port: Number(v) || 5432 })}
                />
              </Group>
              <Group grow>
                <TextInput
                  label="Логин"
                  value={db.user}
                  onChange={(e) => setDb({ ...db, user: e.currentTarget.value })}
                />
                <TextInput
                  label="Имя базы"
                  value={db.dbname}
                  onChange={(e) => setDb({ ...db, dbname: e.currentTarget.value })}
                  description="латиница, цифры, _"
                />
              </Group>
              <PasswordInput
                label="Пароль"
                value={db.password}
                placeholder={db.password_set ? '•••••••• (оставьте пустым, чтобы не менять)' : ''}
                onChange={(e) => setDb({ ...db, password: e.currentTarget.value })}
              />
            </Stack>
          )}

          <Group mt="md">
            <Button variant="light" onClick={onTest} loading={busy} disabled={busy}>
              Проверить подключение
            </Button>
            <Button onClick={save} loading={busy} disabled={busy}>
              {saved ? 'Сохранено' : 'Сохранить подключение'}
            </Button>
            {isAdmin && db.engine === 'postgresql' && (
              <Button color="violet" variant="filled" onClick={onCreate} loading={busy} disabled={busy}>
                Создать базу
              </Button>
            )}
          </Group>
          {msg && <Alert color={msg.color}>{msg.text}</Alert>}

          {isAdmin && (
            <>
              <Text fw={600} mt="lg">Интерфейс</Text>
              <NumberInput
                label="Ширина панели анализа (px)"
                value={ui.analysis_panel_width}
                onChange={(v) => setUi({ ...ui, analysis_panel_width: Number(v) || 720 })}
              />
            </>
          )}
        </Stack>
      </Card>
    </Stack>
  )
}
