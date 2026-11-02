import {FiCheckCircle,FiClock,FiSlash,FiHelpCircle} from 'react-icons/fi'
import type {ReactNode} from 'react'
import {accountLabel,activationLabel} from './customerDisplay'
import './CustomerStatus.css'

type Tone='positive'|'warning'|'negative'|'neutral'
export function StatusBadge({tone='neutral',children}:{tone?:Tone;children:ReactNode}){
  const Icon=tone==='positive'?FiCheckCircle:tone==='warning'?FiClock:tone==='negative'?FiSlash:FiHelpCircle
  return <span className={`customer-status customer-status--${tone}`}><Icon aria-hidden="true" focusable="false"/>{children}</span>
}
export default function CustomerStatus({kind,value}:{kind:'account'|'activation';value:string}){
  const tone:Tone=kind==='account'?(value==='enabled'?'positive':value==='blocked'?'negative':'neutral')
    :value==='active'?'positive':value==='pending'?'warning':value==='suspended'?'negative':'neutral'
  return <StatusBadge tone={tone}>{kind==='account'?accountLabel(value):activationLabel(value)}</StatusBadge>
}
