import React from 'react'

const shapes = {
  Activity: <path d="M3 12h4l3-8 4 16 3-8h4" />,
  ArrowRight: <><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></>,
  BookOpen: <><path d="M12 7c-3-2-6-2-9-1v13c3-1 6-1 9 1 3-2 6-2 9-1V6c-3-1-6-1-9 1Z"/><path d="M12 7v13"/></>,
  Check: <path d="m4 12 5 5L20 6" />,
  ChevronDown: <path d="m6 9 6 6 6-6" />,
  ChevronRight: <path d="m9 6 6 6-6 6" />,
  CircleHelp: <><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 2-2.5 2-2.5 4"/><path d="M12 17h.01"/></>,
  Database: <><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 2 3.6 3 8 3s8-1 8-3V5M4 12v7c0 2 3.6 3 8 3s8-1 8-3v-7"/></>,
  FileJson: <><path d="M6 2h8l5 5v15H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Z"/><path d="M14 2v6h5M9 13l-2 2 2 2m6-4 2 2-2 2"/></>,
  FileText: <><path d="M6 2h8l5 5v15H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Z"/><path d="M14 2v6h5M8 12h8M8 16h8"/></>,
  Layers3: <><path d="m12 2 9 5-9 5-9-5 9-5ZM3 12l9 5 9-5M3 17l9 5 9-5"/></>,
  Play: <path d="m7 4 13 8-13 8V4Z" />,
  Search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
  ShieldCheck: <><path d="m12 2 8 3v6c0 6-4 9-8 11-4-2-8-5-8-11V5l8-3Z"/><path d="m8 12 3 3 5-5"/></>,
  Sparkles: <><path d="m12 2 1.5 5.5L19 9l-5.5 1.5L12 16l-1.5-5.5L5 9l5.5-1.5L12 2ZM19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z"/></>,
  UploadCloud: <><path d="M7 18H5a4 4 0 0 1-1-7.9A7 7 0 0 1 17.3 8 5 5 0 0 1 19 18h-2"/><path d="m12 21 0-9m-4 4 4-4 4 4"/></>,
}

function icon(name) {
  return function Icon({ size = 24, strokeWidth = 2, fill = 'none', className, ...props }) {
    return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{shapes[name]}</svg>
  }
}

export const Activity = icon('Activity')
export const ArrowRight = icon('ArrowRight')
export const BookOpen = icon('BookOpen')
export const Check = icon('Check')
export const ChevronDown = icon('ChevronDown')
export const ChevronRight = icon('ChevronRight')
export const CircleHelp = icon('CircleHelp')
export const Database = icon('Database')
export const FileJson = icon('FileJson')
export const FileText = icon('FileText')
export const Layers3 = icon('Layers3')
export const Play = icon('Play')
export const Search = icon('Search')
export const ShieldCheck = icon('ShieldCheck')
export const Sparkles = icon('Sparkles')
export const UploadCloud = icon('UploadCloud')
