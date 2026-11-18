import {request,download} from './client.js';
export const loadAll=async()=>{
 const [sources,periods,policies,runs,schedules,deliveries,audits,rules_reciprocal,runs_reciprocal]=await Promise.all([
  '/sources','/periods','/policies','/runs','/schedules','/deliveries','/audits','/reciprocal/rules','/reciprocal/runs'
 ].map(p=>request(p)));
 return {sources,periods,policies,runs,schedules,deliveries,audits,rules_reciprocal,runs_reciprocal};
};
export const saveSource=(data,id)=>request('/sources'+(id?'/'+id:''),id?'PUT':'POST',{data});
export const savePolicy=data=>request('/policies','POST',{data});
export const submitRun=data=>request('/runs','POST',data);
export const approveRun=(id,note)=>request('/runs/'+id+'/approve','POST',{note});
export const precheckReciprocalRule=data=>request('/reciprocal/rules/precheck','POST',{data});
export const saveReciprocalRule=data=>request('/reciprocal/rules','POST',{data});
export const submitReciprocalRun=data=>request('/reciprocal/runs','POST',data);
export const approveReciprocalRun=(id,note)=>request('/reciprocal/runs/'+id+'/approve','POST',{note});
export const downloadReciprocalCsv=id=>download('/reciprocal/runs/'+id+'/csv');
