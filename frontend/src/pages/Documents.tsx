import { useState } from 'react'

import { Button, Card, FileInput, Select, Stack, Text, Alert } from '@mantine/core'

import { useQuery } from '@tanstack/react-query'

import { getCases, uploadDocument } from '../api'

import JobProgressBar from '../components/JobProgressBar'



export default function Documents() {

  const [caseId, setCaseId] = useState<string | null>(null)

  const [file, setFile] = useState<File | null>(null)

  const [jobId, setJobId] = useState<string | null>(null)

  const [error, setError] = useState('')

  const [loading, setLoading] = useState(false)

  const { data: cases } = useQuery({ queryKey: ['cases'], queryFn: getCases })



  const onUpload = async () => {

    if (!caseId || !file) return

    setLoading(true)

    setError('')

    setJobId(null)

    try {

      const res = await uploadDocument(caseId, file)

      const id = res?.job?.id as string | undefined

      if (id) {

        setJobId(id)

      } else if (res?.queue_error) {

        setError(`Очередь недоступна: ${res.queue_error}`)

      } else {

        setError('Документ загружен, но задача анализа не создана (проверьте Redis/Celery)')

      }

    } catch (e: unknown) {

      setError(e instanceof Error ? e.message : 'Ошибка загрузки')

    } finally {

      setLoading(false)

    }

  }



  return (

    <Stack>

      <Text size="xl" fw={600}>Документы</Text>

      <Card withBorder padding="lg" style={{ background: '#161B22', borderColor: '#30363D' }}>

        <Stack>

          <Select

            label="Кейс"

            placeholder="Выберите кейс"

            data={(cases || []).map((c: { id: string; title: string }) => ({ value: c.id, label: c.title }))}

            value={caseId}

            onChange={setCaseId}

          />

          <FileInput label="DOCX файл" accept=".docx" value={file} onChange={setFile} />

          <Button onClick={onUpload} loading={loading} disabled={!caseId || !file}>

            Загрузить и запустить анализ

          </Button>

        </Stack>

      </Card>

      {error && <Alert color="red">{error}</Alert>}

      {jobId && <JobProgressBar jobId={jobId} />}

    </Stack>

  )

}

