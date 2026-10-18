export function accountLabel(status:string){
  switch(status){case 'enabled':return 'Habilitada';case 'blocked':return 'Bloqueada';default:return 'Estado não reconhecido'}
}
export function activationLabel(status:string){
  switch(status){case 'pending':return 'Pendente';case 'active':return 'Ativa';case 'suspended':return 'Suspensa';default:return 'Estado não reconhecido'}
}
export function registrationDate(value:unknown){
  if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:\d{2})$/i.test(value))return 'Data indisponível'
  const [year,month,day]=value.slice(0,10).split('-').map(Number)
  const calendar=new Date(0)
  calendar.setUTCFullYear(year!,month!-1,day!)
  if(calendar.getUTCFullYear()!==year||calendar.getUTCMonth()!==month!-1||calendar.getUTCDate()!==day)return 'Data indisponível'
  const instant=new Date(value)
  if(!Number.isFinite(instant.getTime()))return 'Data indisponível'
  return new Intl.DateTimeFormat('pt-BR',{dateStyle:'short',timeStyle:'short',timeZone:'UTC'}).format(instant)+' UTC'
}
