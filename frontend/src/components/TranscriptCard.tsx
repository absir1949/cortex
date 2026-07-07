import { useState } from 'react'
import { useTranscript } from '../api/contents'

interface Props {
  contentId: string
}

/** 「查看原文」入口：点击展开/收起转录原文。
 * 用在信号卡片和内容列表的「看原视频」旁边。
 */
export default function TranscriptToggle({ contentId }: Props) {
  const [open, setOpen] = useState(false)
  const { data: transcript, isLoading, isError } = useTranscript(contentId, open)

  return (
    <>
      <button
        type="button"
        className="transcript-toggle-btn"
        onClick={() => setOpen(!open)}
      >
        {open ? '收起原文' : '查看原文'}
      </button>
      {open && (
        <div className="transcript-block">
          {isLoading && <div className="transcript-block-loading">加载原文...</div>}
          {isError && <div className="transcript-block-loading">无转录</div>}
          {transcript && <div className="transcript-block-body">{transcript}</div>}
        </div>
      )}
    </>
  )
}
