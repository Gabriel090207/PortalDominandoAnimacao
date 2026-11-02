import {test} from 'node:test'
import assert from 'node:assert/strict'
import {createServer} from 'vite'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'

test('customer badges retain text, semantic colors and neutral unknown values',async()=>{
 const vite=await createServer({server:{middlewareMode:true,hmr:false,ws:false,watch:null}})
 try{
  const {default:CustomerStatus}=await vite.ssrLoadModule('/src/pages/Customers/CustomerStatus.tsx')
  for(const [kind,value,tone,label] of [
   ['account','enabled','positive','Habilitada'],['account','blocked','negative','Bloqueada'],
   ['activation','active','positive','Ativa'],['activation','pending','warning','Pendente'],
   ['activation','suspended','negative','Suspensa'],['account','unknown','neutral','Estado não reconhecido'],
   ['activation','','neutral','Estado não reconhecido'],
  ]){
   const markup=renderToStaticMarkup(createElement(CustomerStatus,{kind,value}))
   assert.ok(markup.includes(`customer-status--${tone}`))
   assert.ok(markup.includes(label))
   assert.match(markup,/aria-hidden="true"/)
  }
 }finally{await vite.close()}
})
