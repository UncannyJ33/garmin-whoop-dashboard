/**
 * GarminUpload — reusable drag-and-drop upload widget for Garmin export files.
 *
 * Supported formats: .csv (Activities export), .json (summarized activities),
 * .zip (full account export from Garmin Connect Account Settings).
 *
 * Used in: Onboarding, Settings
 */
import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useGarminUpload } from '../hooks/useApi'
import type { UploadResult } from '../types/api'

interface Props {
  /** Called after a successful import with the result payload. */
  onSuccess?: (result: UploadResult) => void
  /** Compact mode: smaller padding, no help text */
  compact?: boolean
}

type Units = 'miles' | 'km'

function SuccessBanner({ result }: { result: UploadResult }) {
  return (
    <div className="rounded-xl bg-emerald-950 border border-emerald-700 p-4 text-sm space-y-1">
      <p className="font-semibold text-emerald-300">
        Imported {result.imported} record{result.imported !== 1 ? 's' : ''}
        {result.skipped_duplicates > 0 && (
          <span className="text-emerald-500 font-normal">
            {' '}({result.skipped_duplicates} duplicate{result.skipped_duplicates !== 1 ? 's' : ''} skipped)
          </span>
        )}
      </p>
      {result.date_range && (
        <p className="text-slate-400">Date range: {result.date_range}</p>
      )}
      {result.format_detected && (
        <p className="text-slate-500 text-xs capitalize">
          Format: {result.format_detected}
          {result.skipped_errors > 0 && ` · ${result.skipped_errors} rows skipped (parse errors)`}
        </p>
      )}
      {result.training_load_note && (
        <p className="text-slate-500 text-xs">{result.training_load_note}</p>
      )}
    </div>
  )
}

export function GarminUpload({ onSuccess, compact = false }: Props) {
  const [dragging, setDragging] = useState(false)
  const [units, setUnits] = useState<Units>('miles')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [result, setResult] = useState<UploadResult | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const upload = useGarminUpload()

  function pickFile(file: File) {
    setSelectedFile(file)
    setResult(null)
    upload.reset()
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) pickFile(file)
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) pickFile(file)
  }

  function handleSubmit() {
    if (!selectedFile) return
    upload.mutate(
      { file: selectedFile, units },
      {
        onSuccess: (res) => {
          setResult(res)
          setSelectedFile(null)
          if (fileInputRef.current) fileInputRef.current.value = ''
          onSuccess?.(res)
        },
      },
    )
  }

  const isLoading = upload.isPending
  const error = upload.error

  return (
    <div className={`space-y-3 ${compact ? '' : 'p-1'}`}>
      {/* Drop zone */}
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload Garmin export file"
        className={`
          relative flex flex-col items-center justify-center gap-2
          border-2 border-dashed rounded-xl transition-colors cursor-pointer
          ${compact ? 'py-5 px-4' : 'py-8 px-6'}
          ${dragging
            ? 'border-blue-400 bg-blue-950/40'
            : selectedFile
              ? 'border-emerald-600 bg-emerald-950/20'
              : 'border-slate-600 bg-slate-800/40 hover:border-slate-400 hover:bg-slate-800/60'
          }
        `}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click() }}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,.json,.zip,application/zip,text/csv,application/json"
          className="sr-only"
          onChange={handleFileChange}
        />

        {selectedFile ? (
          <>
            <span className="text-2xl select-none">📄</span>
            <p className="text-sm font-medium text-slate-200">{selectedFile.name}</p>
            <p className="text-xs text-slate-400">
              {(selectedFile.size / 1024).toFixed(0)} KB · click to change
            </p>
          </>
        ) : (
          <>
            <span className="text-2xl select-none">⬆️</span>
            <p className="text-sm font-medium text-slate-300">
              Drag & drop or click to browse
            </p>
            <p className="text-xs text-slate-500">CSV, JSON, or Garmin export ZIP · max 50 MB</p>
          </>
        )}
      </div>

      {/* Units toggle (relevant for CSV) */}
      {!compact && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-slate-400 text-xs">Distance units in CSV:</span>
          {(['miles', 'km'] as Units[]).map((u) => (
            <button
              key={u}
              type="button"
              onClick={() => setUnits(u)}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                units === u
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
              }`}
            >
              {u === 'miles' ? 'Miles' : 'Kilometres'}
            </button>
          ))}
        </div>
      )}

      {/* Error */}
      {error && (
        <p className="text-sm text-red-400 bg-red-950/40 border border-red-800 rounded-xl px-3 py-2">
          {error instanceof Error ? error.message : 'Upload failed'}
        </p>
      )}

      {/* Success */}
      {result && <SuccessBanner result={result} />}

      {/* Submit */}
      <button
        type="button"
        disabled={!selectedFile || isLoading}
        onClick={handleSubmit}
        className="w-full rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-40
                   disabled:cursor-not-allowed text-white text-sm font-medium
                   py-2.5 transition-colors flex items-center justify-center gap-2"
      >
        {isLoading ? (
          <>
            <span className="inline-block w-4 h-4 border-2 border-white/30 border-t-white
                             rounded-full animate-spin" />
            Importing…
          </>
        ) : (
          'Import'
        )}
      </button>

      {/* Help link */}
      {!compact && (
        <p className="text-xs text-slate-500 text-center">
          Not sure how to export?{' '}
          <Link to="/help/garmin-export" className="text-blue-400 hover:text-blue-300 underline">
            Step-by-step instructions →
          </Link>
        </p>
      )}
    </div>
  )
}
