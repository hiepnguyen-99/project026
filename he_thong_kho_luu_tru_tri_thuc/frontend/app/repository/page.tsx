"use client";

import Link from "next/link";
import { Children, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, ChevronRight, File, FilePenLine, FilePlus2, Folder, FolderOpen, LayoutGrid, List, LoaderCircle, Search, Trash2, Upload } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { useUploadTasks } from "@/components/upload-task-provider";
import { DashboardData, Document, DocumentDetail, FolderNode, formatDate, MyFolderTree } from "@/lib/api";
import { useBackendData } from "@/lib/hooks";
import { PageHeader, Panel } from "@/components/ui";

type DocumentForm = {
  title: string;
  topic: string;
  doc_type: string;
  visibility: "public" | "private";
  folder_path: string;
  folder_node_id?: string;
  content: string;
};

type FolderTree = {
  [name: string]: FolderTree | { id: string; title: string }[];
};

type TreeRow =
  | { type: "folder"; id: string; name: string; path: string; parentPath: string; depth: number; hasChildren: boolean }
  | { type: "file"; id: string; name: string; path: string; depth: number };

const empty: DashboardData = { user:{code:"",name:"",role:"lecturer",department:"",permissions:[]},stats:{documents:0,private:0,topics:0},documents:[],requests:[],backups:[],audit:[] };
const DOCUMENT_TYPES = ["Đề cương môn học","Kế hoạch giảng dạy","Bài giảng","Slide","Giáo trình","Sách tham khảo","Lab","Bài tập","Đồ án","Đề thi","Đáp án","Ngân hàng câu hỏi","Nghiên cứu khoa học","Tài liệu khác"];
const DEFAULT_DOCUMENT_TYPE = "Tài liệu khác";
const emptyForm: DocumentForm = { title:"", topic:"", doc_type:DEFAULT_DOCUMENT_TYPE, visibility:"public", folder_path:"", folder_node_id:"", content:"" };
const emptyMyTree: MyFolderTree = { policy:null, name:"Kho cua toi", children:[] };
const visibilityLabel = (value: string) => value === "public" ? "Công khai" : "Riêng tư";
const MB = 1024 * 1024;
const MAX_AI_ANALYZE_BYTES = 25 * MB;
const MAX_UPLOAD_BYTES = 250 * MB;
const formatFileSize = (bytes: number) => `${(bytes / MB).toFixed(bytes >= 10 * MB ? 1 : 2)} MB`;
const documentStatusLabel = (status?: Document["status"]) => status === "INDEXED" ? "Đã lập chỉ mục" : status === "FAILED" ? "Xử lý thất bại" : "Đang xử lý AI";
const documentStatusClass = (status?: Document["status"]) => status === "INDEXED" ? "badge-green" : status === "FAILED" ? "badge-red" : "badge-amber";

export default function Repository() {
  const { request, user } = useAuth();
  const { tasks: uploadTasks, startUpload } = useUploadTasks();
  const router = useRouter();
  const { data, loading, error, reload } = useBackendData("/api/dashboard", empty);
  const { data: folderTree, reload: reloadFolderTree } = useBackendData<FolderTree>("/api/folders/tree", {});
  const { data: myFolderTree, reload: reloadMyFolderTree } = useBackendData<MyFolderTree>("/api/my-folder-tree", emptyMyTree);
  const [selected,setSelected]=useState<Document|null>(null);
  const [selectedFolder,setSelectedFolder]=useState("");
  const [query,setQuery]=useState("");
  const [uploadOpen,setUploadOpen]=useState(false);
  const [editorOpen,setEditorOpen]=useState(false);
  const [editing,setEditing]=useState<Document|null>(null);
  const [file,setFile]=useState<File|null>(null);
  const [uploadAsNew,setUploadAsNew]=useState(false);
  const [metadata,setMetadata]=useState({title:"",topic:"",doc_type:DEFAULT_DOCUMENT_TYPE,visibility:"public",folder_path:"",folder_node_id:"",specialization_id:"",course_id:""});
  const [destinationSource,setDestinationSource]=useState<""|"manual"|"ai">("");
  const [documentTypeTouched,setDocumentTypeTouched]=useState(false);
  const [form,setForm]=useState<DocumentForm>(emptyForm);
  const [busy,setBusy]=useState(false);
  const [startingUpload,setStartingUpload]=useState(false);
  const [launchedTaskId,setLaunchedTaskId]=useState("");
  const [message,setMessage]=useState("");
  const virtualFolderTree=useMemo(()=>myFolderTree.children.length?folderTreeFromNodes(myFolderTree.children,data.documents):folderTree,[myFolderTree.children,data.documents,folderTree]);
  const folderOptions=useMemo(()=>flattenFolderNodes(myFolderTree.children),[myFolderTree.children]);
  const docs=useMemo(()=>data.documents.filter(x=>(!selectedFolder||x.folder_path===selectedFolder||x.folder_path.endsWith(`/${selectedFolder}`))&&`${x.title} ${x.topic} ${x.doc_type}`.toLowerCase().includes(query.toLowerCase())),[data.documents,query,selectedFolder]);
  const current=selected||docs[0]||null;
  const updateCandidate=useMemo(()=>data.documents.find(document=>document.owner_code===user?.code&&document.title.trim().toLocaleLowerCase("vi")===metadata.title.trim().toLocaleLowerCase("vi"))||null,[data.documents,metadata.title,user?.code]);
  const canManage=(document:Document)=>user?.role==="admin"||document.owner_code===user?.code;
  const completedUploads=uploadTasks.filter(task=>task.status==="completed").length;
  const launchedTask=uploadTasks.find(task=>task.id===launchedTaskId);
  const launchedProgress=launchedTask?Math.round(launchedTask.uploaded_bytes/launchedTask.total_bytes*100):0;
  const launchedActive=!!launchedTask&&!["completed","failed","pending_confirmation"].includes(launchedTask.status);
  const classificationTicket=launchedTask?.metadata.classification_ticket;
  const finalDestination=useMemo(()=>{
    const selectedNode=metadata.folder_node_id?folderOptions.find(option=>option.id===metadata.folder_node_id):undefined;
    const selectedCourse=metadata.course_id?folderOptions.find(option=>option.id===metadata.course_id):undefined;
    const aiCourse=classificationTicket?.suggested_course_id?folderOptions.find(option=>option.id===classificationTicket.suggested_course_id):undefined;
    if(selectedNode){
      const isFolder=selectedNode.type==="standard_folder"||selectedNode.type==="folder";
      return {
        source:"manual" as const,
        badge:"Manual Selection",
        specialization_id:metadata.specialization_id||null,
        course_id:selectedNode.type==="course"?selectedNode.id:(selectedNode.parent_id||selectedCourse?.id||metadata.course_id||null),
        folder_node_id:selectedNode.id,
        document_type:isFolder?selectedNode.name:metadata.doc_type,
        path:isFolder?selectedNode.path:`${selectedNode.path}/${metadata.doc_type}`,
      };
    }
    if(metadata.course_id&&selectedCourse){
      return {source:"manual" as const,badge:"Manual Selection",specialization_id:metadata.specialization_id||null,course_id:metadata.course_id,folder_node_id:null,document_type:metadata.doc_type,path:`${selectedCourse.path}/${metadata.doc_type}`};
    }
    if(classificationTicket?.suggested_course_id){
      const documentType=documentTypeTouched?metadata.doc_type:(classificationTicket.suggested_document_type||metadata.doc_type);
      const coursePath=aiCourse?.path||[classificationTicket.suggested_specialization,classificationTicket.suggested_course].filter(Boolean).join("/");
      return {source:"ai" as const,badge:"AI Suggested",specialization_id:classificationTicket.suggested_specialization_id||null,course_id:classificationTicket.suggested_course_id,folder_node_id:null,document_type:documentType,path:[coursePath,documentType].filter(Boolean).join("/")};
    }
    return {source:"manual" as const,badge:"Manual Selection",specialization_id:metadata.specialization_id||null,course_id:metadata.course_id||null,folder_node_id:metadata.folder_node_id||null,document_type:metadata.doc_type,path:metadata.folder_path||metadata.doc_type};
  },[classificationTicket,documentTypeTouched,folderOptions,metadata]);

  useEffect(()=>{
    if(completedUploads)void Promise.all([reload(),reloadFolderTree(),reloadMyFolderTree()]);
  },[completedUploads,reload,reloadFolderTree,reloadMyFolderTree]);

  useEffect(()=>{
    const ticket=launchedTask?.metadata.classification_ticket;
    if(!ticket||launchedTask?.status!=="pending_confirmation")return;
    setDestinationSource(current=>current||"ai");
    setMetadata(x=>({
      ...x,
      topic:x.topic||ticket.suggested_course||ticket.suggested_specialization||"",
      visibility:x.visibility||ticket.suggested_visibility,
      doc_type:documentTypeTouched?x.doc_type:(ticket.suggested_document_type||x.doc_type),
    }));
  },[documentTypeTouched,launchedTask?.id,launchedTask?.status]);

  function selectFile(nextFile:File|null){
    setFile(nextFile);
    setLaunchedTaskId("");
    setMessage("");
    setDestinationSource("");
    setDocumentTypeTouched(false);
    if(!nextFile)return;
    setMetadata(x=>({...x,title:x.title||nextFile.name.replace(/\.[^.]+$/,"").replaceAll("_"," ")}));
    if(nextFile.size>MAX_UPLOAD_BYTES){
      setMessage(`File ${formatFileSize(nextFile.size)} vượt giới hạn tải lên 250 MB.`);
    }else if(nextFile.size>MAX_AI_ANALYZE_BYTES){
      setMessage(`File ${formatFileSize(nextFile.size)} sẽ được tải theo từng phần và AI phân tích ở chế độ nền.`);
    }
  }

  function openCreate(){
    setEditing(null);setForm(emptyForm);setMessage("");setEditorOpen(true);
  }

  async function openEdit(document:Document){
    setBusy(true);setMessage("");
    try{
      const detail=await request<DocumentDetail>(`/api/documents/${document.id}`);
      setEditing(document);
      setForm({title:detail.title,topic:detail.topic,doc_type:detail.doc_type,visibility:detail.visibility,folder_path:detail.folder_path||"",folder_node_id:detail.folder_node_id||"",content:detail.content});
      setEditorOpen(true);
    }catch(err){setMessage(err instanceof Error?err.message:"Không thể mở tài liệu để sửa.");}
    finally{setBusy(false);}
  }

  async function saveDocument(){
    setBusy(true);setMessage("");
    try{
      await request(editing?`/api/documents/${editing.id}`:"/api/documents",{method:editing?"PUT":"POST",body:JSON.stringify(form)});
      setEditorOpen(false);setEditing(null);await reload();
    }catch(err){setMessage(err instanceof Error?err.message:"Không thể lưu tài liệu.");}
    finally{setBusy(false);}
  }

  async function removeDocument(document:Document){
    if(!confirm(`Đưa "${document.title}" vào thùng rác?`))return;
    setBusy(true);setMessage("");
    try{
      await request(`/api/documents/${document.id}`,{method:"DELETE"});
      if(selected?.id===document.id)setSelected(null);
      await reload();
    }catch(err){setMessage(err instanceof Error?err.message:"Không thể xóa tài liệu.");}
    finally{setBusy(false);}
  }

  async function uploadFile(){
    if(!file)return;
    if(file.size>MAX_UPLOAD_BYTES){setMessage("File vượt giới hạn tải lên 250 MB.");return;}
    setStartingUpload(true);setMessage("");
    try{
      const updateExisting=updateCandidate&&!uploadAsNew;
      const taskId=await startUpload(file,{...metadata,visibility:metadata.visibility as "public"|"private",existing_document_id:updateExisting?updateCandidate.id:undefined});
      setLaunchedTaskId(taskId);
    }catch(err){setMessage(err instanceof Error?err.message:"Tải lên thất bại.");}
    finally{setStartingUpload(false);}
  }

  async function confirmUpload(){
    if(!launchedTask||launchedTask.status!=="pending_confirmation")return;
    setStartingUpload(true);setMessage("");
    try{
      await request(`/api/uploads/${launchedTask.id}/confirm`,{method:"POST",body:JSON.stringify({specialization_id:finalDestination.specialization_id,course_id:finalDestination.course_id,folder_node_id:finalDestination.folder_node_id,document_type:finalDestination.document_type,visibility:metadata.visibility})});
      await Promise.all([reload(),reloadFolderTree(),reloadMyFolderTree()]);
      setUploadOpen(false);setFile(null);setLaunchedTaskId("");
    }catch(err){setMessage(err instanceof Error?err.message:"Không thể xác nhận lưu tài liệu.");}
    finally{setStartingUpload(false);}
  }

  return <div><PageHeader eyebrow="Kho tri thức" title="Kho tài liệu" description={`${data.stats.documents} tài liệu đang được lưu trong hệ thống.`} actions={<><button className="btn-secondary" onClick={openCreate}><FilePlus2 size={15}/>Tạo tài liệu</button><button className="btn-primary" onClick={()=>{setMessage("");setUploadOpen(true)}}><Upload size={15}/>Tải tệp lên</button></>}/>
    {(error||message||myFolderTree.message)&&<p className="mb-4 rounded bg-amber-50 p-3 text-xs text-amber-800">{error||message||myFolderTree.message}</p>}
    <div className="grid gap-4 xl:grid-cols-[minmax(280px,30%)_minmax(0,1fr)]">
      <Panel title={myFolderTree.policy?"Kho của tôi theo Master Tree":"Kho tài liệu"} description={myFolderTree.policy?`Policy active: ${myFolderTree.policy.title}`:"Fallback theo folder_path hiện có"}><FolderNavigation tree={virtualFolderTree} selectedPath={selectedFolder} selectedFileId={selected?.id||""} onSelectFolder={path=>{setSelectedFolder(path);setSelected(null)}} onOpenFile={id=>router.push(`/documents/${id}`)}/></Panel>
      <Panel title={selectedFolder||"Tất cả tài liệu"} description={loading?"Đang tải...":`${docs.length} tài liệu`}><div className="flex flex-wrap gap-2 border-b border-[var(--border)] p-3"><div className="relative min-w-48 flex-1"><Search className="muted absolute left-3 top-2.5" size={15}/><input className="field pl-9" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Tìm tài liệu trong thư mục..."/></div><button className="icon-btn" aria-label="Dạng danh sách"><List size={15}/></button><button className="icon-btn" aria-label="Dạng lưới"><LayoutGrid size={15}/></button></div>
        <div className="table-shell"><table className="data-table"><thead><tr><th>Tên</th><th>Loại</th><th>Chủ sở hữu</th><th>Cập nhật</th><th>Quyền</th><th>Thao tác</th></tr></thead><tbody>{docs.map(d=><tr key={d.id} onClick={()=>setSelected(d)} className={current?.id===d.id?"bg-[var(--soft)]":""}><td><div className="flex items-center gap-2"><div className="h-8 w-8 rounded bg-red-50 text-red-600 grid place-items-center"><File size={15}/></div><div><Link href={`/documents/${d.id}`} className="font-bold hover:text-blue-600">{d.title}</Link><span className="muted block text-[10px]">{d.topic}</span><span className={`badge mt-1 ${documentStatusClass(d.status)}`}>{documentStatusLabel(d.status)}</span></div></div></td><td>{d.doc_type}</td><td>{d.owner_code}</td><td>{formatDate(d.updated_at)}</td><td><span className={`badge ${d.visibility==="public"?"badge-green":"badge-amber"}`}>{visibilityLabel(d.visibility)}</span></td><td>{canManage(d)&&<div className="flex gap-1"><button className="icon-btn" aria-label="Sửa tài liệu" disabled={busy} onClick={e=>{e.stopPropagation();openEdit(d)}}><FilePenLine size={15}/></button><button className="icon-btn text-red-600" aria-label="Xóa tài liệu" disabled={busy} onClick={e=>{e.stopPropagation();removeDocument(d)}}><Trash2 size={15}/></button></div>}</td></tr>)}</tbody></table></div>
        {!docs.length&&<p className="muted p-8 text-center text-xs">Thư mục này chưa có tài liệu trực tiếp.</p>}
      </Panel>
    </div>
    {editorOpen&&<Modal onClose={()=>setEditorOpen(false)}><p className="eyebrow">{editing?"Chỉnh sửa tài liệu":"Tạo tài liệu thủ công"}</p><h2 className="page-title mt-1">{editing?"Cập nhật tài liệu":"Thêm tài liệu mới"}</h2><DocumentFields form={form} setForm={setForm}/>{message&&<p className="mt-3 rounded bg-amber-50 p-2 text-xs text-amber-800">{message}</p>}<div className="mt-5 flex justify-end gap-2"><button className="btn-secondary" onClick={()=>setEditorOpen(false)}>Hủy</button><button disabled={busy||!form.title||!form.topic||!form.content} className="btn-primary" onClick={saveDocument}>{busy&&<LoaderCircle className="animate-spin" size={15}/>}Lưu tài liệu</button></div></Modal>}
    {uploadOpen&&<Modal onClose={()=>setUploadOpen(false)}><p className="eyebrow">Nhập tài liệu có hỗ trợ AI</p><h2 className="page-title mt-1">Tải tài liệu mới</h2><label className="mini-grid mt-5 block rounded-xl border-2 border-dashed border-blue-300 p-8 text-center"><Upload className="mx-auto text-blue-600"/><strong className="mt-3 block text-sm">{file?.name||"Chọn tệp để tải lên"}</strong>{file&&<span className="muted mt-1 block text-xs">{formatFileSize(file.size)} · tải theo chunk · AI xử lý nền · tối đa 250 MB</span>}<input type="file" className="hidden" disabled={launchedActive} onChange={e=>selectFile(e.target.files?.[0]||null)}/></label><div className="mt-4 grid gap-3 sm:grid-cols-2"><input className="field" placeholder="Tên tài liệu" value={metadata.title} onChange={e=>{setMetadata(x=>({...x,title:e.target.value}));setUploadAsNew(false)}}/><input className="field" placeholder="Chủ đề" value={metadata.topic} onChange={e=>setMetadata(x=>({...x,topic:e.target.value}))}/><select className="field" value={metadata.doc_type} onChange={e=>{setDocumentTypeTouched(true);setMetadata(x=>({...x,doc_type:e.target.value}))}}>{DOCUMENT_TYPES.map(type=><option key={type} value={type}>{type}</option>)}</select><select className="field" value={metadata.visibility} onChange={e=>setMetadata(x=>({...x,visibility:e.target.value as "public"|"private"}))}><option value="public">Công khai</option><option value="private">Riêng tư</option></select>{updateCandidate&&<div className="sm:col-span-2 rounded-xl border border-blue-200 bg-blue-50 p-3 text-xs text-blue-900"><strong className="block">Đã có tài liệu cùng tên: v{updateCandidate.current_version}</strong><p className="mt-1">Mặc định file này sẽ trở thành phiên bản v{updateCandidate.current_version+1}. Bản cũ vẫn được giữ để so sánh, tải xuống và backup.</p><label className="mt-3 flex items-center gap-2 font-semibold"><input type="checkbox" checked={uploadAsNew} onChange={e=>setUploadAsNew(e.target.checked)}/>Tạo thành tài liệu mới riêng biệt</label></div>}{folderOptions.length>0&&<FolderNodePicker options={folderOptions} value={metadata.folder_node_id} onChange={option=>{setDestinationSource(option?"manual":"");setDocumentTypeTouched(option?.type==="standard_folder"||option?.type==="folder"?true:documentTypeTouched);setMetadata(x=>({...x,folder_node_id:option?.id||"",folder_path:option?.path||x.folder_path,course_id:option?.type==="course"?option.id:x.course_id,doc_type:option?.type==="standard_folder"||option?.type==="folder"?option.name:x.doc_type}))}}/>}<FolderPicker tree={folderTree} value={metadata.folder_path} onChange={folder_path=>{setDestinationSource(folder_path?"manual":destinationSource);setMetadata(x=>({...x,folder_path}))}}/><input className="field sm:col-span-2" placeholder="Hoặc nhập đường dẫn thư mục mới" value={metadata.folder_path} onChange={e=>setMetadata(x=>({...x,folder_path:e.target.value}))}/></div>{launchedTask&&<div className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-3"><div className="flex justify-between text-xs font-bold text-blue-900"><span>{launchedTask.status==="uploading"?"Đang tải lên":launchedTask.status==="uploaded"?"Đã tải file gốc":launchedTask.status==="analyzing"?"Đang AI phân tích":launchedTask.status==="saving_metadata"?"Đang lưu metadata":launchedTask.status==="pending_confirmation"?"Chờ xác nhận phân loại":launchedTask.status==="processing"?"Đang xử lý AI":launchedTask.status==="completed"?"Đã lưu":"Thất bại"}</span><span>{launchedProgress}%</span></div><div className="progress mt-2"><i style={{width:`${launchedProgress}%`}}/></div><p className="muted mt-2 text-[10px]">{formatFileSize(launchedTask.uploaded_bytes)} / {formatFileSize(launchedTask.total_bytes)}</p>{launchedTask.error&&<p className="mt-2 text-xs text-red-600">{launchedTask.error}</p>}</div>}{classificationTicket&&launchedTask?.status==="pending_confirmation"&&<div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-950"><div className="flex items-start justify-between gap-3"><div><strong className="block text-sm">AI Recommendation</strong><p className="mt-1">Độ tin cậy AI: {Math.round(classificationTicket.confidence*100)}%</p></div><span className="badge badge-amber">Chờ xác nhận</span></div><p className="mt-2 text-[11px]">{classificationTicket.reasoning}</p>{classificationTicket.confidence<0.7&&<p className="mt-2 rounded-lg border border-amber-300 bg-white px-3 py-2 font-semibold text-amber-800">AI is not confident. Please select destination manually.</p>}{classificationTicket.suggestions.length>0&&<div className="mt-3 grid gap-2">{classificationTicket.suggestions.slice(0,3).map(option=><button key={option.course_id} type="button" className={`rounded-lg border px-3 py-2 text-left transition ${metadata.course_id===option.course_id?"border-blue-500 bg-white text-blue-700":"border-amber-200 bg-white/70 hover:border-blue-300"}`} onClick={()=>{setDestinationSource("manual");setMetadata(x=>({...x,folder_node_id:"",specialization_id:option.specialization_id,course_id:option.course_id,topic:option.course}))}}><strong className="block">{option.course} ({Math.round(option.confidence*100)}%)</strong><span>{option.specialization}</span></button>)}</div>}<div className="mt-3 grid gap-2 sm:grid-cols-2"><select className="field" value={metadata.doc_type} onChange={e=>{setDocumentTypeTouched(true);setMetadata(x=>({...x,doc_type:e.target.value}))}}>{DOCUMENT_TYPES.map(type=><option key={type} value={type}>{type}</option>)}</select><select className="field" value={metadata.visibility} onChange={e=>setMetadata(x=>({...x,visibility:e.target.value as "public"|"private"}))}><option value="public">Công khai</option><option value="private">Riêng tư</option></select></div><div className="mt-3 rounded-lg border border-blue-200 bg-white p-3"><div className="flex items-center justify-between gap-2"><strong className="text-sm">Final Destination</strong><span className={`badge ${finalDestination.source==="manual"?"badge-green":"badge-amber"}`}>{finalDestination.badge}</span></div><p className="mt-2 break-all font-semibold">Final save location: {finalDestination.path||"Chưa chọn học phần"}</p></div></div>}{message&&<p className="mt-3 rounded bg-amber-50 p-2 text-xs text-amber-800">{message}</p>}<p className="muted mt-3 text-[11px]">Bạn có thể đóng cửa sổ hoặc chuyển trang sau khi bắt đầu. Theo dõi tiến trình tại bảng Upload gần đây.</p><div className="mt-5 flex justify-end gap-2"><button className="btn-secondary" onClick={()=>setUploadOpen(false)}>Đóng</button><button disabled={!file||file.size>MAX_UPLOAD_BYTES||!metadata.title||(!metadata.topic&&!classificationTicket)||startingUpload||launchedActive} className="btn-primary" onClick={classificationTicket&&launchedTask?.status==="pending_confirmation"?confirmUpload:uploadFile}>{(startingUpload||launchedActive)&&<LoaderCircle className="animate-spin" size={15}/>} {classificationTicket&&launchedTask?.status==="pending_confirmation"?"Xác nhận lưu":launchedActive?"Đang xử lý...":updateCandidate&&!uploadAsNew?`Cập nhật lên v${updateCandidate.current_version+1}`:"Bắt đầu tải lên"}</button></div></Modal>}
  </div>;
}

function FolderNavigation({tree,selectedPath,selectedFileId,onSelectFolder,onOpenFile}:{tree:FolderTree;selectedPath:string;selectedFileId:string;onSelectFolder:(path:string)=>void;onOpenFile:(id:string)=>void}){
  const [expanded,setExpanded]=useState<Set<string>>(()=>new Set([""]));
  const [folderQuery,setFolderQuery]=useState("");
  const [focusIndex,setFocusIndex]=useState(0);
  const treeRef=useRef<HTMLDivElement>(null);
  const normalizedQuery=folderQuery.trim().toLocaleLowerCase("vi");

  const rows=useMemo(()=>{
    const result:TreeRow[]=[{type:"folder",id:"root",name:"Tất cả tài liệu",path:"",parentPath:"",depth:0,hasChildren:Object.keys(tree).some(name=>name!=="_documents")}];

    function matchesFolder(node:FolderTree,name:string):boolean{
      if(!normalizedQuery||name.toLocaleLowerCase("vi").includes(normalizedQuery))return true;
      return Object.entries(node).some(([childName,child])=>childName!=="_documents"&&!Array.isArray(child)&&matchesFolder(child,childName));
    }

    function walk(node:FolderTree,parentPath:string,depth:number){
      Object.entries(node).filter(([name,value])=>name!=="_documents"&&!Array.isArray(value)&&matchesFolder(value as FolderTree,name)).sort(([a],[b])=>a.localeCompare(b,"vi")).forEach(([name,value])=>{
        const child=value as FolderTree;
        const path=parentPath?`${parentPath}/${name}`:name;
        const childFolders=Object.entries(child).filter(([childName,childValue])=>childName!=="_documents"&&!Array.isArray(childValue));
        const files=Array.isArray(child._documents)?child._documents:[];
        result.push({type:"folder",id:`folder:${path}`,name,path,parentPath,depth,hasChildren:childFolders.length>0||files.length>0});
        if(expanded.has(path)||normalizedQuery){
          walk(child,path,depth+1);
          files.forEach(file=>result.push({type:"file",id:file.id,name:file.title,path,depth:depth+1}));
        }
      });
    }

    if(expanded.has("")||normalizedQuery)walk(tree,"",1);
    return result;
  },[tree,expanded,normalizedQuery]);

  useEffect(()=>{
    setFocusIndex(index=>Math.min(index,Math.max(0,rows.length-1)));
  },[rows.length]);

  function focusRow(index:number){
    const next=Math.max(0,Math.min(rows.length-1,index));
    setFocusIndex(next);
    requestAnimationFrame(()=>treeRef.current?.querySelector<HTMLElement>(`[data-tree-index="${next}"]`)?.focus());
  }

  function toggleFolder(path:string){
    setExpanded(current=>{
      const next=new Set(current);
      if(next.has(path))next.delete(path);else next.add(path);
      return next;
    });
    onSelectFolder(path);
  }

  function activate(row:TreeRow){
    if(row.type==="folder")toggleFolder(row.path);else onOpenFile(row.id);
  }

  function onTreeKeyDown(event:React.KeyboardEvent,row:TreeRow,index:number){
    if(event.key==="ArrowDown"){event.preventDefault();focusRow(index+1);}
    else if(event.key==="ArrowUp"){event.preventDefault();focusRow(index-1);}
    else if(event.key==="Home"){event.preventDefault();focusRow(0);}
    else if(event.key==="End"){event.preventDefault();focusRow(rows.length-1);}
    else if(event.key==="Enter"||event.key===" "){event.preventDefault();activate(row);}
    else if(event.key==="ArrowRight"&&row.type==="folder"){
      event.preventDefault();
      if(!expanded.has(row.path))toggleFolder(row.path);else focusRow(index+1);
    }else if(event.key==="ArrowLeft"&&row.type==="folder"){
      event.preventDefault();
      if(expanded.has(row.path))toggleFolder(row.path);
      else focusRow(Math.max(0,rows.findIndex(candidate=>candidate.type==="folder"&&candidate.path===row.parentPath)));
    }
  }

  return <div className="p-2">
    <div className="relative mb-2"><Search className="muted absolute left-3 top-2.5" size={14}/><input className="field pl-9" value={folderQuery} onChange={event=>setFolderQuery(event.target.value)} placeholder="Tìm thư mục..."/></div>
    <div ref={treeRef} role="tree" aria-label="Cây thư mục" className="max-h-[65vh] overflow-auto text-[12px]">
      {rows.map((row,index)=>{
        const isFolder=row.type==="folder";
        const isExpanded=isFolder&&(expanded.has(row.path)||!!normalizedQuery);
        const isSelected=isFolder?selectedPath===row.path:selectedFileId===row.id;
        return <button key={`${row.type}:${row.id}`} type="button" role="treeitem" aria-expanded={isFolder?isExpanded:undefined} aria-selected={isSelected} data-tree-index={index} tabIndex={focusIndex===index?0:-1} onFocus={()=>setFocusIndex(index)} onKeyDown={event=>onTreeKeyDown(event,row,index)} onClick={()=>activate(row)} onDoubleClick={()=>row.type==="file"&&onOpenFile(row.id)} className={`flex w-full items-center gap-1 rounded-md py-1.5 pr-2 text-left outline-none transition hover:bg-[var(--soft)] focus:ring-2 focus:ring-blue-400 ${isSelected?"bg-blue-50 font-bold text-blue-700":""}`} style={{paddingLeft:`${6+row.depth*16}px`}}>
          {isFolder?(isExpanded?<ChevronDown size={14}/>:<ChevronRight size={14}/>):<span className="w-[14px]"/>}
          {isFolder?(isExpanded?<FolderOpen className="shrink-0 text-amber-500" size={15}/>:<Folder className="shrink-0 text-amber-500" size={15}/>):<File className="shrink-0 text-slate-500" size={14}/>}
          <span className="truncate">{row.name}</span>
        </button>;
      })}
      {!rows.length&&<p className="muted p-3 text-xs">Không tìm thấy thư mục.</p>}
    </div>
    <p className="muted mt-2 border-t border-[var(--border)] px-2 pt-2 text-[10px]">Dùng phím mũi tên để điều hướng, Enter để mở.</p>
  </div>;
}

function Modal({children,onClose}:{children:React.ReactNode;onClose:()=>void}){
  const parts=Children.toArray(children);
  const header=parts.slice(0,2);
  const footer=parts.slice(-1);
  const body=parts.slice(2,-1);
  useEffect(()=>{
    const previous=document.body.style.overflow;
    document.body.style.overflow="hidden";
    return ()=>{document.body.style.overflow=previous;};
  },[]);
  return <div className="fixed inset-0 z-50 grid place-items-center overflow-hidden bg-slate-950/60 p-3 sm:p-4" onClick={onClose}>
    <div className="app-card flex max-h-[90vh] w-[95vw] flex-col overflow-hidden md:w-[80vw] xl:w-[1000px] 2xl:w-[1100px]" onClick={e=>e.stopPropagation()}>
      <div className="shrink-0 border-b border-[var(--border)] px-5 py-4">{header}</div>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{body}</div>
      <div className="sticky bottom-0 z-10 shrink-0 border-t border-[var(--border)] bg-[var(--card)] px-5 py-4">{footer}</div>
    </div>
  </div>;
}

function folderTreeFromNodes(nodes:FolderNode[],documents:Document[]):FolderTree{
  const root:FolderTree={};
  const byNodeId=new Map<string,{id:string;title:string}[]>();
  documents.forEach(document=>{
    if(document.folder_node_id)byNodeId.set(document.folder_node_id,[...(byNodeId.get(document.folder_node_id)||[]),{id:document.id,title:document.title}]);
  });
  function add(node:FolderNode,target:FolderTree){
    const child:FolderTree={};
    const files=byNodeId.get(node.id)||[];
    if(files.length)child._documents=files;
    node.children.forEach(item=>add(item,child));
    target[node.name]=child;
  }
  nodes.forEach(node=>add(node,root));
  return root;
}

function flattenFolderNodes(nodes:FolderNode[],depth=0):Array<FolderNode&{depth:number}>{
  return nodes.flatMap(node=>[
    {...node,depth},
    ...flattenFolderNodes(node.children,depth+1),
  ]).filter(node=>node.type!=="department"&&node.type!=="faculty");
}

function FolderNodePicker({options,value,onChange}:{options:Array<FolderNode&{depth:number}>;value:string;onChange:(option:(FolderNode&{depth:number})|undefined)=>void}){
  return <div className="sm:col-span-2 rounded-xl border border-blue-200 bg-blue-50 p-3">
    <strong className="block text-xs text-blue-900">Chọn nhánh trong Master Tree</strong>
    <p className="muted mt-1 text-[10px]">Giảng viên chỉ thấy và upload vào các nhánh thuộc nhóm chuyên môn đã chọn.</p>
    <select className="field mt-3" value={value} onChange={event=>onChange(options.find(item=>item.id===event.target.value))}>
      <option value="">Chọn nhánh được phép upload</option>
      {options.map(option=><option key={option.id} value={option.id}>{"--".repeat(option.depth)} {option.path}</option>)}
    </select>
  </div>;
}

function FolderPicker({tree,value,onChange}:{tree:FolderTree;value:string;onChange:(path:string)=>void}){
  const selected=value.split("/").filter(Boolean);
  const levels:{options:string[];selected:string}[]=[];
  let node=tree;

  for(let depth=0;depth<=selected.length;depth++){
    const options=Object.keys(node).filter(name=>name!=="_documents").sort((a,b)=>a.localeCompare(b,"vi"));
    if(!options.length)break;
    levels.push({options,selected:selected[depth]||""});
    const next=selected[depth]?node[selected[depth]]:undefined;
    if(!next||Array.isArray(next))break;
    node=next;
  }

  return <div className="sm:col-span-2 rounded-xl border border-[var(--border)] bg-[var(--soft)] p-3">
    <div className="flex items-center justify-between gap-3">
      <div><strong className="block text-xs">Chọn thư mục có sẵn</strong><span className="muted text-[10px]">Chọn thư mục cha để hiện các thư mục con.</span></div>
      {value&&<button type="button" className="text-[11px] font-bold text-blue-600" onClick={()=>onChange("")}>Bỏ chọn</button>}
    </div>
    {levels.length?<div className="mt-3 grid gap-2 sm:grid-cols-2">{levels.map((level,depth)=><select key={depth} className="field" value={level.selected} onChange={e=>onChange([...selected.slice(0,depth),e.target.value].filter(Boolean).join("/"))}><option value="">Chọn thư mục cấp {depth+1}</option>{level.options.map(name=><option key={name} value={name}>{name}</option>)}</select>)}</div>:<p className="muted mt-3 text-xs">Chưa có thư mục cũ để lựa chọn.</p>}
    {value&&<p className="mt-2 break-all text-[11px]"><span className="muted">Đường dẫn đã chọn: </span><strong>{value}</strong></p>}
  </div>;
}

function DocumentFields({form,setForm}:{form:DocumentForm;setForm:React.Dispatch<React.SetStateAction<DocumentForm>>}){
  return <div className="mt-5 grid gap-3 sm:grid-cols-2"><input className="field" placeholder="Tên tài liệu" value={form.title} onChange={e=>setForm(x=>({...x,title:e.target.value}))}/><input className="field" placeholder="Chủ đề" value={form.topic} onChange={e=>setForm(x=>({...x,topic:e.target.value}))}/><select className="field" value={form.doc_type} onChange={e=>setForm(x=>({...x,doc_type:e.target.value}))}>{DOCUMENT_TYPES.map(type=><option key={type} value={type}>{type}</option>)}</select><select className="field" value={form.visibility} onChange={e=>setForm(x=>({...x,visibility:e.target.value as DocumentForm["visibility"]}))}><option value="public">Công khai</option><option value="private">Riêng tư</option></select><input className="field sm:col-span-2" placeholder="Thư mục lưu (không bắt buộc)" value={form.folder_path} onChange={e=>setForm(x=>({...x,folder_path:e.target.value}))}/><textarea className="field min-h-48 sm:col-span-2" placeholder="Nội dung tài liệu" value={form.content} onChange={e=>setForm(x=>({...x,content:e.target.value}))}/></div>;
}


