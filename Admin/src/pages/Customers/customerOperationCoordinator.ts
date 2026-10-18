/** Per customer detail only. Holds uncertain writes until explicit read-back. */
export function createCustomerOperationCoordinator(){
  let owner:symbol|undefined
  const listeners=new Set<()=>void>()
  function publish(){listeners.forEach(listener=>listener())}
  return {
    getSnapshot:()=>owner,
    subscribe(listener:()=>void){listeners.add(listener);return()=>{listeners.delete(listener)}},
    acquire(candidate:symbol){
      if(owner!==undefined&&owner!==candidate)return false
      if(owner===undefined){owner=candidate;publish()}
      return true
    },
    release(candidate:symbol){if(owner===candidate){owner=undefined;publish()}},
  }
}
export type CustomerOperationCoordinator=ReturnType<typeof createCustomerOperationCoordinator>
