import {test} from 'node:test'
import assert from 'node:assert/strict'
import {createServer} from 'vite'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {createPurchaseConfirmationStore} from '../src/pages/Customers/purchaseConfirmationStore.ts'
import {AdminApiError} from '../src/services/adminApi.ts'

test('purchase presentation is access-management information, no financial indicators or activation',async()=>{
 const vite=await createServer({server:{middlewareMode:true,hmr:false,ws:false,watch:null}})
 try{
  const {PurchaseConfirmationView}=await vite.ssrLoadModule('/src/pages/Customers/PurchaseConfirmation.tsx')
  const {CustomerFacts}=await vite.ssrLoadModule('/src/pages/Customers/CustomerDetail.tsx')
  for(const approved of [true,false]){
   const store=createPurchaseConfirmationStore(()=>{},async()=>({customer_id:'synthetic',approved_purchase_recorded:approved,current_payment_validity:'not_verified',requires_kirvano_review:true}))
   const render=()=>renderToStaticMarkup(createElement(PurchaseConfirmationView,{confirmationStore:store}))
   assert.match(render(),/Consultando confirmação/);await store.load('synthetic')
   const markup=render();assert.match(markup,approved?/Sim/:/Não encontrada/)
   assert.match(markup,/Em caso de dúvida, confira a compra diretamente na Kirvano/)
   for(const forbidden of ['current_payment_validity','not_verified','R$','Ativar acesso','nunca pagou','pagamento válido'])assert.ok(!markup.includes(forbidden))
  }
  const failed=createPurchaseConfirmationStore(()=>{},async()=>{throw new AdminApiError('unavailable',503)})
  await failed.load('synthetic')
  const markup=renderToStaticMarkup(createElement(PurchaseConfirmationView,{confirmationStore:failed}))
  assert.match(markup,/Não foi possível consultar a confirmação da compra/);assert.match(markup,/Consultar confirmação novamente/)
  assert.ok(!markup.includes('Não encontrada'))
  for(const activation of ['pending','active','suspended']){
   const facts=renderToStaticMarkup(createElement(CustomerFacts,{customer:{customer_id:'synthetic',email:'customer@example.test',account_status:'blocked',activation_status:activation,created_at:''}}))
   assert.match(facts,/Status de ativação/);assert.match(facts,/Bloqueada/)
   assert.match(facts,activation==='pending'?/Pendente/:activation==='active'?/Ativa/:/Suspensa/)
  }
 }finally{await vite.close()}
})
