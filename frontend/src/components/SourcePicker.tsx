import { Badge, Card, FileInput, Group, SimpleGrid, Stack, Switch, Text, Textarea, TextInput } from '@mantine/core'
import {
  IconBrandTelegram,
  IconBrandVk,
  IconClipboardText,
  IconFileText,
  IconFileTypePdf,
  IconLink,
  IconWorld,
} from '@tabler/icons-react'
import type { IngestSourceType } from '../api'

export type SourceDraft = {
  sourceType: string
  file: File | null
  text: string
  url: string
  includeComments: boolean
}

const ICONS: Record<string, typeof IconFileText> = {
  docx: IconFileText,
  pdf: IconFileTypePdf,
  paste: IconClipboardText,
  url: IconWorld,
  telegram: IconBrandTelegram,
  vk: IconBrandVk,
}

const FALLBACK_SOURCES: IngestSourceType[] = [
  {
    id: 'docx',
    label: 'Документ DOCX',
    description: 'Текстовый документ Microsoft Word (.docx).',
    input_kind: 'file',
    accept: ['.docx'],
    needs_internet: 'never',
    include_comments: false,
    status: 'ready',
    placeholder: '',
    hint: 'Один файл .docx на кейс.',
  },
  {
    id: 'pdf',
    label: 'Документ PDF',
    description: 'Текстовый слой PDF.',
    input_kind: 'file',
    accept: ['.pdf'],
    needs_internet: 'never',
    include_comments: false,
    status: 'ready',
    placeholder: '',
    hint: 'Сканы без OCR пока не разбираются.',
  },
  {
    id: 'paste',
    label: 'Вставленный текст',
    description: 'Произвольный текст, вставленный в форму.',
    input_kind: 'text',
    accept: [],
    needs_internet: 'never',
    include_comments: false,
    status: 'ready',
    placeholder: 'Вставьте текст для анализа…',
    hint: '',
  },
  {
    id: 'url',
    label: 'Ссылка или HTML',
    description: 'Страница по URL или сохранённый HTML.',
    input_kind: 'url_or_file',
    accept: ['.html', '.htm'],
    needs_internet: 'optional',
    include_comments: false,
    status: 'ready',
    placeholder: 'https://example.com/article',
    hint: 'Нет сети — приложите HTML-файл.',
  },
  {
    id: 'telegram',
    label: 'Группа / канал Telegram',
    description: 'Публичные посты и комментарии.',
    input_kind: 'url_or_file',
    accept: ['.html', '.htm'],
    needs_internet: 'optional',
    include_comments: true,
    status: 'expanding',
    placeholder: 'https://t.me/username',
    hint: '',
  },
  {
    id: 'vk',
    label: 'Паблик ВКонтакте',
    description: 'Посты стены и комментарии.',
    input_kind: 'url_or_file',
    accept: ['.html', '.htm'],
    needs_internet: 'optional',
    include_comments: true,
    status: 'expanding',
    placeholder: 'https://vk.com/public…',
    hint: '',
  },
]

type Props = {
  value: SourceDraft
  onChange: (next: SourceDraft) => void
  sources?: IngestSourceType[]
  online?: boolean | null
}

export function defaultSourceDraft(): SourceDraft {
  return { sourceType: 'docx', file: null, text: '', url: '', includeComments: true }
}

export function resolveSources(items?: IngestSourceType[]): IngestSourceType[] {
  return items && items.length ? items : FALLBACK_SOURCES
}

export default function SourcePicker({ value, onChange, sources, online }: Props) {
  const items = resolveSources(sources)
  const spec = items.find((s) => s.id === value.sourceType) || items[0]
  const Icon = ICONS[spec?.id || ''] || IconLink
  const accept = (spec?.accept || []).join(',')
  const needsNet = spec?.needs_internet === 'optional' || spec?.needs_internet === 'required'
  const showUrl = spec?.input_kind === 'url' || spec?.input_kind === 'url_or_file'
  const showFile = spec?.input_kind === 'file' || spec?.input_kind === 'url_or_file'
  const showText = spec?.input_kind === 'text'
  const offlineNeedFile = online === false && needsNet && spec?.input_kind === 'url_or_file'

  const patch = (partial: Partial<SourceDraft>) => onChange({ ...value, ...partial })

  return (
    <Stack gap="sm">
      <Group justify="space-between" align="flex-end">
        <Text size="sm" fw={500}>Что анализируем</Text>
        {online != null && (
          <Badge size="sm" variant="light" color={online ? 'teal' : 'orange'}>
            {online ? 'интернет есть' : 'интернета нет'}
          </Badge>
        )}
      </Group>
      <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="sm">
        {items.map((s) => {
          const SelectedIcon = ICONS[s.id] || IconFileText
          const active = s.id === value.sourceType
          return (
            <Card
              key={s.id}
              withBorder
              padding="sm"
              radius="md"
              onClick={() => patch({ sourceType: s.id, file: null })}
              style={{
                cursor: 'pointer',
                background: active ? '#1f3a56' : '#161B22',
                borderColor: active ? '#4dabf7' : '#30363D',
              }}
            >
              <Group gap="xs" wrap="nowrap" align="flex-start">
                <SelectedIcon size={20} stroke={1.5} />
                <div>
                  <Group gap={6}>
                    <Text size="sm" fw={600}>{s.label}</Text>
                    {s.status === 'expanding' && (
                      <Badge size="xs" variant="light" color="violet">расширяем</Badge>
                    )}
                  </Group>
                  <Text size="xs" c="dimmed" lineClamp={2}>{s.description}</Text>
                </div>
              </Group>
            </Card>
          )
        })}
      </SimpleGrid>

      {spec && (
        <Stack gap="xs">
          <Group gap="xs">
            <Icon size={16} />
            <Text size="sm" c="dimmed">{spec.hint || spec.description}</Text>
          </Group>
          {offlineNeedFile && (
            <Text size="sm" c="orange">
              Без интернета укажите сохранённый HTML-файл.
            </Text>
          )}
          {showUrl && !offlineNeedFile && (
            <TextInput
              label="Ссылка"
              placeholder={spec.placeholder}
              value={value.url}
              onChange={(e) => patch({ url: e.currentTarget.value })}
            />
          )}
          {showText && (
            <Textarea
              label="Текст"
              placeholder={spec.placeholder}
              minRows={6}
              autosize
              maxRows={16}
              value={value.text}
              onChange={(e) => patch({ text: e.currentTarget.value })}
            />
          )}
          {showFile && (
            <FileInput
              label={spec.input_kind === 'url_or_file'
                ? (offlineNeedFile ? 'HTML-файл (обязательно)' : 'Или файл')
                : 'Файл'}
              accept={accept || undefined}
              value={value.file}
              onChange={(file) => patch({ file })}
              clearable
            />
          )}
          {spec.include_comments && (
            <Switch
              label="Учитывать комментарии пользователей"
              checked={value.includeComments}
              onChange={(e) => patch({ includeComments: e.currentTarget.checked })}
            />
          )}
        </Stack>
      )}
    </Stack>
  )
}

export function sourceReady(draft: SourceDraft, spec?: IngestSourceType, _online?: boolean | null): boolean {
  if (!spec) return false
  if (spec.input_kind === 'file') return !!draft.file
  if (spec.input_kind === 'text') return !!draft.text.trim()
  if (spec.input_kind === 'url' || spec.input_kind === 'url_or_file') {
    return !!draft.url.trim() || !!draft.file
  }
  return false
}

export function defaultCaseTitle(draft: SourceDraft): string {
  if (draft.file?.name) return draft.file.name.replace(/\.[^.]+$/, '')
  if (draft.url.trim()) {
    try {
      const u = new URL(draft.url.trim())
      return u.hostname + (u.pathname !== '/' ? u.pathname : '')
    } catch {
      return draft.url.trim().slice(0, 80)
    }
  }
  const line = draft.text.trim().split('\n').find((s) => s.trim())
  if (line) return line.slice(0, 80)
  return 'Новый кейс'
}
