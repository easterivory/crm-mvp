import { useEffect, useState } from 'react'
import { X } from 'lucide-react'

function Photo({ file, onRemove }: { file: File; onRemove: () => void }) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    const preview = URL.createObjectURL(file)
    setUrl(preview)
    return () => URL.revokeObjectURL(preview)
  }, [file])
  return (
    <div className="relative h-20 w-20 shrink-0 overflow-hidden rounded-lg border border-white/10">
      {url ? <img src={url} alt={file.name} className="h-full w-full object-cover" /> : null}
      <button type="button" onClick={onRemove} title={`Убрать ${file.name}`} className="absolute right-1 top-1 flex h-6 w-6 items-center justify-center rounded-md bg-black/70 text-white">
        <X size={14} />
      </button>
    </div>
  )
}

export default function PhotoAlbumDraft({ files, onRemove }: { files: File[]; onRemove: (index: number) => void }) {
  return (
    <div className="mb-3 border-b border-white/10 pb-3">
      <p className="mb-2 text-xs text-gray-400">Альбом · {files.length} фото</p>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {files.map((file, index) => <Photo key={`${index}:${file.name}:${file.lastModified}`} file={file} onRemove={() => onRemove(index)} />)}
      </div>
    </div>
  )
}
