import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {Presentation,PresentationFile} from 'file:///C:/Users/a2189/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs';
const work='C:/Users/a2189/uv-envs/hip-cross-sectional-area';
const build=work+'/tmp/grant_ppt';
const assets=work+'/tmp/grant_figure/deliverables';
const skill='C:/Users/a2189/.codex/plugins/cache/openai-primary-runtime/presentations/26.1011.11113/skills/presentations';
await fs.mkdir(build,{recursive:true});
await fs.mkdir(work+'/output/grant_ppt',{recursive:true});
const fontPolicy={basis:'design',families:['Meiryo']};
const p=Presentation.create({slideSize:{width:1650,height:850}});
const s=p.slides.add();s.background.fill='#ffffff';
function txt(name,text,x,y,w,h,size,bold=false,color='#1d2730',align='center'){
 const q=s.shapes.add({name,geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 q.text=text;q.text.style={typeface:'Meiryo',fontSize:size,bold,color,alignment:align,insets:0};return q;
}
async function img(name,file,x,y,w,h){const b=await fs.readFile(assets+'/'+file);s.images.add({name,blob:b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength),contentType:'image/png',alt:name,fit:'contain',position:{left:x,top:y,width:w,height:h}});}
txt('CT heading','CT画像（3断面）',22,12,410,36,26,true);
txt('3D heading','股関節周囲筋の三次元表示',625,12,1000,36,26,true);
const files=['01_ilium','02_midpoint','03_greater_trochanter'];
const labels=['腸骨部','中間レベル','大転子頂部付近'];
for(let i=0;i<3;i++){
 const y=60+i*250;
 txt('CT level '+(i+1),`${i+1}  ${labels[i]}`,22,y,410,25,18.5);
 await img('CT '+labels[i],'ct_'+files[i]+'_plain.png',22.5,y+26,410,213.81);
 txt('Right marker '+i,'R',29,y+32,15,20,14,false,'#ffffff');
 txt('Left marker '+i,'L',406,y+32,15,20,14,false,'#ffffff');
}
s.shapes.add({name:'AI extraction arrow',geometry:'rightArrow',position:{left:470,top:334,width:137.5,height:137},fill:'#eef1f3',line:{fill:'#59646e',width:2}});
txt('AI extraction label','AIによる\n筋抽出',474,371,110,54,16,true);
txt('Anterior label','前面',625,55,500,30,19.5);
txt('Posterior label','後面',1130,55,500,30,19.5);
await img('Anterior 3D','gluteal_context_anterior.png',625,90,500,600);
await img('Posterior 3D','gluteal_context_posterior.png',1130,90,500,600);
for(const [x,label,color] of [[660,'中殿筋','#337aba'],[905,'小殿筋','#de4f3b'],[1155,'腸腰筋','#9ca3ab']]){
 s.shapes.add({name:label+' color',geometry:'rect',position:{left:x,top:730,width:22,height:22},fill:color,line:{fill:'none',width:0}});
 txt(label+' legend',label,x+32.5,727,210,28,17,false,'#1d2730','left');
}
txt('Anatomic context note','骨盤・大腿骨を位置関係の参照として表示',625,770,1000,30,15,false,'#59646e');
s.speakerNotes.text='元画像：提供DICOM input/sampleDATA、InstanceNumber 110、149、188。WL40/WW400。中殿筋・小殿筋と骨は既存抽出、腸腰筋はTotalSegmentator無償totalタスク。自動抽出の輪郭は専門家による最終確認が必要。ハムストリングスは近位部の抽出が不十分なため本図には含めない。構成参考：岩佐ら、Hip Joint 2025;51:51–55。論文画像の転載ではなく提供CTから独立作成。CTと3Dは埋め込み画像、見出し・凡例・矢印は個別の編集可能オブジェクト。';
await fs.writeFile(build+'/preview.png',new Uint8Array(await (await p.export({slide:s,format:'png',scale:1})).arrayBuffer()));
const candidate=build+'/candidate.pptx';await(await PresentationFile.exportPptx(p)).save(candidate);
const {finalizePresentation}=await import(pathToFileURL(skill+'/container_tools/artifact_tool_utils.mjs').href);
const result=await finalizePresentation({workspaceDir:work,candidatePath:candidate,finalPath:work+'/output/grant_ppt/grant_figure_editable.pptx',pythonExecutable:'C:/Users/a2189/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu',`${1650*9525},${850*9525}`,'--validate-heading-fit'],explicitTotalSlideCount:1,fontPolicy,verifyArtifactToolImport:true,receiptPath:build+'/validation.json'});
console.log(JSON.stringify(result));
