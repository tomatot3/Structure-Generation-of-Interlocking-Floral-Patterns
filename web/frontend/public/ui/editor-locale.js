(() => {
 const paper=new URLSearchParams(location.search);
 const view=location.pathname.startsWith('/editor')?'editor':'appearance';
 if(paper.get('workspace')==='1')document.documentElement.classList.add('editor-embedded');
 const entries="结构编辑|Structure editor\n当前结构|Current structure\n直接绘制工具|Drawing tools\n选择|Select\n新增枝|Add branch\n新增分枝|New branch\n根点范围|Root range\n枝尖范围|Tip region\n曲线包络|Curve envelope\n禁区|Exclusion zone\n约束工具|Constraints\n下载|Download\n撤销|Undo\n重做|Redo\n保存版本|Save version\n保存并继续外观设计|Save and edit appearance\n下载 SVG|Download SVG\n下载 PNG|Download PNG\n下载 JSON|Download JSON\n会话与视图|Session and view\n结构|Structure\n视图模式|View mode\n三周期|Three repeats\n整图|Whole strip\n双周期|Two repeats\n枝组|Branch group\n分枝数量状态|Branch requirements\n选中枝：|Selected branch\n必需|Required\n可选|Optional\n禁用|Excluded\n删除|Delete\n禁区范围|Exclusion scope\n全局|Global\n当前枝组|Current group\n当前父枝|Current parent\n当前层级|Current level\n正在载入结构…|Loading structure…\n结构编辑画布|Structure editing canvas\n选择分枝后直接拖动根点、枝尖或控制柄|Select a branch and drag its root, tip or handles.\n曲线|Curve\n允许区域|Allowed region\n相邻周期|Adjacent repeats\n枝组数量|Branch group counts\n选择分枝查看所属枝组|Select a branch to see its group.\n图形约束|Geometry constraints\n尚未设置区域|No regions defined\n保存的版本|Saved versions\n暂无保存版本|No saved versions\n载入|Load\n比较|Compare\n正在读取保存记录…|Loading saved versions…\n拖动根点、枝尖或控制柄|Drag the root, tip or control handles\n从父枝直接拖出|Drag out from a parent branch\n允许区域/禁区|Allowed and exclusion regions\n在画布自由圈定|Draw an outline on the canvas\n包络|Envelope\n拖两条边界曲线|Drag the two boundary curves\n向研究团队提交修改|Share edits with the research team\n提交完全自愿。仅保存版本不会提交研究数据。|Sharing is voluntary. Saving a version does not share research data.\n我同意提交原始结构、修改后的结构、生成参数和修改记录，用于后续研究和参数改进。|I agree to share the source and edited structures, generation parameters and edit record for further research.\n可选：为什么这样修改？|Optional note about this edit\n提交修改|Share edits\n选择分枝后直接拖动根点、枝尖或 Bézier 控制柄|Select a branch and drag its root, tip or Bézier handles.\n在主干或 L1/L2 父枝上按下，向空白处拖出一条新枝|Drag from the main vine or an L1/L2 parent to add a branch.\n选择分枝后，在它的父枝上拖出允许挂载的弧长区间|Select a branch, then drag along its parent to set the allowed attachment range.\n选择分枝后，在画布上按住并自由圈出枝尖允许区域|Select a branch and draw the allowed tip region.\n选择分枝，拖动橙色边界控制点定义曲线允许包络|Select a branch and drag the amber handles to define its envelope.\n选择禁区范围后，在画布上按住并自由圈出禁区|Choose an exclusion scope, then draw the region on the canvas.\n父枝长度为零|The parent branch has zero length.\n无法计算父枝局部框架|Could not calculate the parent’s local coordinate frame.\n父枝没有有效线段|The parent has no valid curve segments.\n请先选择一条分枝，再创建曲线包络。|Select a branch before creating an envelope.\n当前禁区范围需要先选择一条分枝|Select a branch for this exclusion scope.\n请先选择一条分枝，再圈出枝尖允许区域。|Select a branch before drawing a tip region.\n当前固定深度编辑器只允许新增到 L3。|This editor supports branches up to L3.\n主藤、花位与承花路径保持固定；拖动分枝进行编辑|The main vine, flower sites and flower-bearing paths are fixed. Drag a branch to edit it.\n正在保存结构…|Saving structure…\n已保存，可继续编辑或下载。|Saved. Continue editing or download the structure.\n枝组视图需要先选择一条分枝。|Select a branch to open its group view.\n已载入保存的结构。|Saved structure loaded.\n载入所选版本会放弃当前未保存的修改，是否载入？|Load this version and discard unsaved edits?\n下载失败，请重试。|Download failed. Try again.\n请先勾选自愿提交说明。|Confirm that you agree to share the edits.\n已提交，用于后续参数分析。当前生成参数保持不变。|Submitted for further research. The current generation settings are unchanged.\n外观编辑|Appearance editor\n方案|Plan\n分组|Grouping\n编辑|Edit\n交付|Delivery\n读取项目…|Loading project…\n还原修改|Reset edits\n结构与外观对照|Show structure alongside artwork\n保存项目|Save project\n打开项目|Open project\n器型应用|Apply to vessel\n导出设计|Export design\n构成对象|Design objects\n结构方案|Structure\n导入结构方案|Import structure\n外观要求|Appearance brief\n导出渲染条件|Export render inputs\n生成结果对应的结构|Structure used for rendering\n导入生成结果|Import rendering\n生成记录|Generation record\n模型、实际提示或生成记录位置|Model, prompt or generation record location\n查看结构提示|View structure prompt\n该外观的实际生成记录|Rendering record\n将条件包用于外观生成，再导入单个重复单元。|Use the input package to render the design, then import one repeat.\n校正归属|Correct assignments\n检查对象|Inspect object\n在原图上整理片段。已调整的枝形、花头和删减会保留。|Reassign parts of the original image. Existing branch edits, flowers and deletions are retained.\n归属画笔|Assignment brush\n画笔宽度|Brush width\n清除本次涂选|Clear selection\n归入对象|Assign to\n归入所选对象|Assign to selected object\n暂不归属|Mark as unassigned\n新建、合并与挂接|Create, merge and reattach\n新对象名称|New object name\n例如：右上叶饰|Example: upper right leaf\n依附对象|Attachment target\n将涂选部分新建为叶饰|Create a leaf ornament from selection\n纠正当前对象的依附记录|Change the attachment record\n将当前对象整体并入归入对象|Merge into the target object\n结构配准|Align structure\n拖动配准点使结构贴合原图，再重新分组。|Drag alignment points onto the original image, then regroup.\n按配准重新分组|Regroup using alignment\n撤销上一次归属校正|Undo last reassignment\n继续编辑设计|Continue editing\n对象|Object\n花头大小|Flower size\n替换花头|Replace flower\n原花头|Original flower\n花头1|Flower 1\n花头2|Flower 2\n调整花位|Move flower site\n叶饰大小|Leaf size\n替换叶饰|Replace leaf\n原叶饰|Original leaf\n叶饰1|Leaf 1\n叶饰2|Leaf 2\n移除对象|Remove object\n恢复对象|Restore object\n连续边饰|Repeating border\n带高（mm）|Band height (mm)\n重复单元数|Repeats\n器型应用 · 3D|Apply to vessel · 3D\n查看外观接缝|Inspect seam\n调整重复接缝|Edit repeat seam\n两侧端点和切向联动，修改在各周期同步。|The ends and tangents are linked across repeats.\n下载可编辑SVG|Download editable SVG\n下载连续SVG|Download repeating SVG\n下载PNG预览|Download PNG preview\n版本与对照|Versions and comparison\n版本名称|Version name\n保存设计版本|Save design version\n与当前设计对照|Compare with current design\n载入选中版本|Load selected version\n来源与设计任务|Source and design brief\n来源|Source\n文献、页码或藏品|Publication, page or collection object\n采用的构成解释|Interpretation of the composition\n设计任务|Design brief\n保存来源与任务|Save source and brief\n设计|Design\n关闭对照|Close comparison\n已保存版本|Saved version\n当前设计|Current design\n连续接缝|Repeat seam\n关闭|Close\n查看范围|View range\n接缝线|Seam line\n标出所选对象|Highlight selected object\n整幅高度|Full height\n单元右侧|Right edge\n单元左侧|Left edge\n相邻单元拼接|Adjacent repeats\n点击枝叶可返回编辑；同一对象在各重复单元中同步更新。|Select a leaf or branch to edit it across repeats.\n返回编辑|Return to editor\n器型|Vessel\n宽沿瓷盘|Wide-rim plate\n敞口碗|Open bowl\n直身杯|Straight cup\n搭配纹样|Companion motif\n海水龙纹|Dragon and waves\n留白|None\n边饰重复|Border repeats\n边饰宽度|Border width\n靠近边缘|Edge position\n拖动旋转，滚轮缩放。边饰采用当前编辑结果。|Drag to rotate and scroll to zoom. The vessel uses the edited border.\n拖动旋转，滚轮缩放|Drag to rotate, scroll to zoom\n查看角度|View angle\n整体|Front\n低角度|Low angle\n俯视|Top\n保存图片|Save image\n下载模型|Download model\n处理中…|Working…\n操作失败|Operation failed\n操作未完成|Operation did not finish\n更新矢量…|Updating vectors…\n原图归属校正 · 设计修改保留|Correct original assignments · design edits retained\n移除整个枝组|Remove the branch group\n该部分暂未确定结构归属，可在分组中重新指定。|This element is unassigned. Assign it in Grouping.\n花藤受保护。修改花位时，承花路径随接合点调整。|The vine is protected. Moving a flower also moves its attachment.\n替换或缩放花头；勾选调整花位后拖动中心点。|Replace or scale the flower. Enable Move flower site to drag its center.\n整条分枝的控制柄同时显示。拖根点沿主藤换挂接位置，拖枝尖调长度和走势；子枝跟随。|Drag the root to change its attachment on the vine, or the tip to change length and direction. Child branches follow.\n拖控制柄调整整条子枝；根点沿父枝移动，枝尖可直接拖动。|Drag control handles to reshape the child, or move its root along the parent and drag its tip.\n拖控制柄调整叶饰走势；根点沿主藤移动。|Drag handles to reshape the leaf, or move its root along the vine.\n控制点|Control point\n校准尚未应用|Alignment not yet applied\n结构辅助分组|Structure-assisted grouping\n结构底稿|Reference structure\n当前外观|Current rendering\n分组已更新，现有设计修改保留|Grouping updated. Design edits retained.\n涂选要重新归属的部分|Paint over the parts to reassign\n结束接缝调整|Finish seam editing\n已恢复项目|Project restored\n已导入，请核对结构配准与归属|Rendering imported. Check alignment and assignments.\n不依附其他对象|Independent object\n已载入结构。导出条件后生成外观，再导入图像。|Structure loaded. Export render inputs, then import the resulting image.\n未填写|No note\n尚无外观生成记录|No rendering record\n选择已保存版本|Select a saved version\n版本已保存|Version saved\n来源与任务已保存|Source and brief saved\n结构已载入，上一设计已保存为版本|Structure loaded. The previous design was saved as a version.\n已撤销归属校正，设计修改保留|Reassignment undone. Design edits retained.\n归属已更新，枝形与删减保留|Assignments updated. Branch edits and deletions retained.\n选择生成时使用的结构|Select the structure used for rendering\n以当前结构配准（没有原始生成记录）|Align to current structure (no original render record)\n导入时使用此结构快照。之后的设计修改会另存为版本。|Use this structure snapshot on import. Subsequent edits can be saved as a separate version.\n当前结构只作恢复参照，不登记为已确认的生成输入。|Use the current structure for alignment only.\n已选中对象；修改会同步到所有重复单元|Object selected. Edits apply across repeats.\n正在载入当前边饰…|Loading the current border…\n正在导出…|Exporting…\n瓷盘|plate\n碗|bowl\n杯|cup\n出向控制柄|Outgoing handle\n入向控制柄|Incoming handle\n根点|Root\n枝尖|Tip\n连接点|Join\n主藤|Main vine\n面板|Controls\n纹样设定|Pattern setup\n导入结构线稿|Import structural drawing\n纹样样式|Pattern style\n导出结构底图|Export base drawing\n绘图所用的结构版本|Structure version used for the artwork\n导入纹样图像|Import pattern image\n绘图备注|Artwork notes\n可记下绘图方式、提示词或文件出处|Drawing method, prompt or file source\n结构提示词|Structure prompt\n原图与绘图提示词|Source drawing and artwork prompt\n整理花叶归属|Refine flower and leaf grouping\n在原图上涂选花叶，重新指定归属。现有的枝形、花头和删减会保留。|Paint over flowers or leaves in the original image to reassign them. Existing branch, flower and removal edits are kept.\n标为未归属|Mark as unassigned\n重设挂接对象|Change attachment\n结构对位|Align the drawing\n拖动控制点，让线稿贴合原图，再按对位结果重新分组。|Drag the handles to align the drawing with the artwork, then regroup.\n按对位重新分组|Regroup using this alignment\n撤销上次分组调整|Undo last grouping adjustment\n预览连续接缝|Preview joins between repeats\n微调连续接缝|Refine joins between repeats\n完成接缝调整|Finish adjusting joins\n设计版本|Design versions\n图样来源与备注|Pattern sources and notes\n采用的构型|Chosen configuration\n保存来源与备注|Save sources and notes\n来源与备注已保存|Sources and notes saved.\n器面边饰来自当前设计。拖动旋转，滚轮或双指缩放。|The vessel uses the current border design. Drag to rotate, then scroll or pinch to zoom.\n视角|View angle\n全景|Full view\n低角|Low angle\n调整花叶归属 · 保留现有设计|Refine grouping · existing design retained\n主藤形态已锁定。移动花位时，承花路径会随花位调整。|The vine shape is locked. Moving a flower site also adjusts its bearing path.\n对位调整尚未应用|Alignment changes have not been applied\n按结构整理花叶|Group flowers and leaves using the drawing\n结构线稿|Structural drawing\n当前纹样|Current pattern\n结构线稿已载入。|Structural drawing ready.\n选择绘图时使用的结构|Choose the drawing used for this artwork\n直接匹配当前结构|Align to the current drawing\n导入图像时会按此版本对位，后续改动另存为版本。|The image is aligned to this version. Later edits are saved separately.\n当前结构只用于对位，绘图原本另行记录。|The current drawing is used for alignment only. The original drawing is recorded separately.\n涂选要调整归属的花叶|Paint over the flowers or leaves to reassign\n正在更新设计…|Updating the design…\n正在将边饰贴合器面…|Fitting the border to the vessel…\n点选分枝，拖动根点、枝尖或控制柄调整形态|Select a branch and drag its root, tip or handles to shape it.\n主藤、花位与承花路径已锁定，可直接拖动分枝。|The vine, flower sites and bearing paths are locked. Drag branches to edit them.\n枝组明细|Branch group details\n约束边界|Drawing constraints\n历史版本|Version history\n尚未设置绘制约束。可从「约束工具」划定范围。|No drawing constraints yet. Use Constraints to set a range.\n贡献修改案例|Contribute an edited example\n我同意将原始结构、修改后的结构、构图参数和修改记录提交给研究团队，用于后续研究和参数改进。|I agree to share the original and edited structures, composition parameters and edit history with the research team for future research and parameter refinement.\n修改思路（可选）|Notes on your edits (optional)\n提交案例|Submit example\n案例已提交。|Example submitted.\n当前结构仅作对位参照。|Use the current drawing as an alignment reference.\n分组已更新，保留现有设计。|Grouping updated. Existing edits are kept.\n已撤销上次分组调整。|Last grouping adjustment undone.\n花叶归属已更新，保留枝形和删减。|Grouping updated. Branch edits and removals are kept.\n结构线稿已载入，上一版设计已保存。|The drawing is ready. The previous design is saved as a version.\n请选择绘图所用的结构版本|Choose the structure version used for the artwork.\n操作指南|Guide to the tools\n技术档案|Technical archive\n选好样式后导出结构底图。绘制完成后，导入单个重复单元的纹样图像，再分组编辑。|Choose a style and export the base drawing. Once the artwork is ready, import the image for a single repeat, then group and edit it.\n保留来源和绘图线索，便于日后查阅。|Keep the source and drawing notes for future reference.\n提交为自愿选择，保存版本时不会提交案例。|Sharing is optional. Saving a version does not submit the example.\n拖动根点、枝尖或控制柄调整分枝。|Drag the root, tip or handles to shape the branch.\n几何细节|Geometry details\n父枝|Parent branch\n子枝|Child branch\n三级枝|Third-level branch\n暂无绘图备注|No artwork notes\n包络边界相交|Envelope boundaries intersect".split('\n').map(line=>line.split('|'));
 const english=new Map(entries);
 english.set("将当前对象并入目标对象","Merge the current object into the target");
 english.set("案例已提交。","Example submitted.");
 for(const [zh,en] of [['绘图','Drawing'],['编辑历史','Edit history'],['存档','Archive'],['展台光色','Display lighting'],['素瓷白台','Porcelain light'],['深靛夜赏','Indigo night'],['瓷盘','Plate'],['碗','Bowl'],['杯','Cup']])english.set(zh,en);
 english.set("渲染条件.zip","rendering-condition.zip");
 english.set("可编辑设计.zip","editable-design.zip");
 english.set("设计项目.json","design-project.json");
 const pieces=[
  [/^共 (\d+) 枝（(\d+) 父枝 · (\d+) 子枝(?: · (\d+) 三级枝)?）$/,(_,total,parents,children,third)=>total+' branches · '+parents+' parent · '+children+' child'+(third?' · '+third+' third-level':'')],
  [/^(.+?) · (父枝|子枝|三级枝|分枝) · 挂接位置 ([\d.]+)%$/,(_,name,level,pos)=>label(name)+' · '+label(level)+' · Attachment '+pos+'%'],
  [/^整条边饰约 ([\d.]+) mm 宽 · (\d+) 个重复单元$/,(_,width,repeats)=>'Border width approx. '+width+' mm · '+repeats+' repeats'],
  [/^图集编号 (.+)$/,(_,id)=>'Collection no. '+id],
  [/^图样日期 (.+)$/,(_,date)=>'Artwork date '+date],
  [/^绘图备注 · (.+)$/,(_,note)=>'Artwork notes · '+note],
  [/^底图 (\d+) · (.+)$/,(_,n,date)=>'Base drawing '+n+' · '+date],
  [/^(.+?) · L(\d+) · 挂接位置 ([\d.]+)%$/,(_,name,level,pos)=>label(name)+' · L'+level+' · Attachment '+pos+'%'],
  [/^弓高 ([\d.]+) · 曲率符号变化 (\d+)( · 警告：包络边界相交)?$/,(_,bow,changes,warning)=>'Sagitta '+bow+' · Curvature sign changes '+changes+(warning?' · Envelope boundaries intersect':'')],
  [/^(\d+) 条分枝：父枝 (\d+)，子枝 (\d+)(?:，三级枝 (\d+))?$/,(_,total,parents,children,third)=>total+' branches: '+parents+' parent, '+children+' child'+(third?', '+third+' third-level':'')],
  [/^当前枝组：必需 (\d+) 条，可选 (\d+) 条，禁用 (\d+) 条。$/,(_,required,optional,excluded)=>'Branch group: '+required+' required, '+optional+' optional, '+excluded+' excluded.'],
  [/^根点区间 (\d+) · 枝尖区 (\d+) · 曲线包络 (\d+) · 禁区 (\d+)(?: · (\d+) 个包络相交)?$/,(_,roots,tips,envelopes,regions,intersections)=>'Root ranges '+roots+' · Tip regions '+tips+' · Envelopes '+envelopes+' · Exclusions '+regions+(intersections?' · Intersections '+intersections:'')],
  [/^该分枝有 (\d+) 条后代。确定删除整棵子树；取消则保留。$/,(_,n)=>'Delete this branch and its '+n+' descendants?'],
  [/^父枝\s*(\d+)$/,(_,n)=>'Parent '+n],
  [/^子枝\s*(\d+)$/,(_,n)=>'Child '+n],
  [/^(?:主花|花位)\s*(\d+)$/,(_,n)=>'Flower site '+n],
  [/^承花路径\s*(\d+)$/,(_,n)=>'Flower-bearing path '+n],
  [/^沿藤叶饰\s*(\d+)$/,(_,n)=>"Vine leaf ornament "+n],
  [/^叶饰\s*(\d+)$/,(_,n)=>'Leaf ornament '+n],
  [/^新增分枝\s*(\d+)$/,(_,n)=>'New branch '+n],
  [/^未归属\s*(\d+)?$/,(_,n)=>'Unassigned'+(n?' '+n:'')],
  [/^此结构已保存 (\d+) 个版本。$/,(_,n)=>n+' versions saved for this structure.'],
  [/^与所选版本比较：共同分枝 (\d+) 条，当前新增 (\d+) 条，当前删除 (\d+) 条；平均挂接位置差 ([\d.]+)%，状态变化 (\d+) 条。$/,(_,same,added,removed,delta,status)=>'Compared with the selected version: '+same+' shared, '+added+' added, '+removed+' removed. Mean attachment difference '+delta+'%; '+status+' status changes.'],
  [/^已涂选 (\d+) 笔$/,(_,n)=>n+' brush strokes selected'],
  [/^总宽约 ([\d.]+) mm · 等比缩放$/,(_,n)=>'Approx. '+n+' mm wide · proportional scaling'],
  [/^带高 ([\d.]+) mm · 单元宽 ([\d.]+) mm$/,(_,a,b)=>'Band height '+a+' mm · repeat width '+b+' mm'],
  [/^结构 · (.+)$/,(_,x)=>'Structure · '+label(x)],
  [/^外观 · (.+)$/,(_,x)=>'Appearance · '+label(x)],
  [/^移除(.+)$/,(_,x)=>'Remove '+label(x)],
  [/^配对记录 (.+)$/,(_,x)=>'Pair record '+x],
  [/^已导入外观；生成说明：(.+)$/,(_,x)=>'Rendering imported · generation note: '+label(x)],
  [/^已导出 (.+)$/,(_,x)=>'Exported '+x],
  [/^已提交：(.+)$/,(_,x)=>'Submitted: '+x],
  [/^编辑器载入失败：(.+)$/,(_,x)=>'Editor could not load: '+label(x)],
  [/^请求失败 \((\d+)\)$/,(_,n)=>'Request failed ('+n+')'],
  [/^找不到父枝 (.+)$/,(_,x)=>'Parent branch not found: '+x],
  [/^已切换到真实 (.+)$/,(_,x)=>'Loaded '+x],
  [/^(.+?)(?:第(\d+)段)?(出向控制柄|入向控制柄|根点|枝尖|控制点|连接点)(\d*)$/,(_,name,segment,control,n)=>label(name)+' · '+(segment?'segment '+segment+' · ':'')+label(control)+(n?' '+n:'')],
  [/^(.+) 及其子枝$/,(_,x)=>label(x)+' and its children'],
 ];
 function label(txt){
  if(english.has(txt))return english.get(txt);
  for(const [pattern,map] of pieces){const match=txt.match(pattern);if(match)return map(...match);}
  return txt;
 }
 let lang=paper.get('lang')==='en'||(!paper.has('lang')&&localStorage.getItem('papera-language')==='en')?'en':'zh';
 const translations=new WeakMap();
 const attributes=['title','aria-label','alt','placeholder'];
 function replace(node,key){
  const before=key?node.getAttribute(key):node.nodeValue;
  if(!before)return;
  let record=translations.get(node);
  if(!record){record=new Map();translations.set(node,record);}
  const previous=record.get(key);
  const source=previous?.display===before?previous.source:before;
  const out=lang==='en'?source.replace(/\S[\s\S]*\S|\S/,text=>label(text)):source;
  record.set(key,{source,display:out});
  if(before!==out){if(key)node.setAttribute(key,out);else node.nodeValue=out;}
 }
 function walk(node) {
  if(node.nodeType===Node.TEXT_NODE){
   if(!node.parentElement?.closest('script,style,textarea,pre,[contenteditable]'))replace(node);
   return;
  }
  if(node.nodeType!==Node.ELEMENT_NODE&&node.nodeType!==Node.DOCUMENT_NODE)return;
  for(const key of attributes)if(node.hasAttribute?.(key))replace(node,key);
  for(const child of node.childNodes)walk(child);
 }
 function localize(){
  document.documentElement.lang=lang==='en'?'en':'zh-CN';
  walk(document);
 }
 function dirty(value){
  if(window.parent!==window)window.parent.postMessage({type:'papera-'+view+'-dirty',dirty:value},location.origin);
 }
 function catalog(id){
  const m=/^(sw\d)-([a-z])-(\d+)$/i.exec(id||'');
  return m?m[1].toUpperCase()+'–'+m[2].toUpperCase()+' · '+m[3]:id;
 }
 window.AtlasEditor={text:s=>lang==='en'?label(s):s,setDirty:dirty,catalog};
 window.addEventListener('message',e=>{
  if(e.origin!==location.origin||e.source!==window.parent||e.data?.type!=='papera-ui-language')return;
  if(e.data.lang==='en'||e.data.lang==='zh'){if(lang!==e.data.lang){lang=e.data.lang;localize();}}
 });
 document.addEventListener('DOMContentLoaded',()=>{
  localize();
  new MutationObserver(records=>{
   for(const r of records){
    if(r.type==='attributes')replace(r.target,r.attributeName);
    else if(r.type==='characterData')walk(r.target);
    else for(const node of r.addedNodes)walk(node);
   }
  }).observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:attributes});
  if(window.parent!==window)window.parent.postMessage({type:'papera-ui-ready'},location.origin);
 });
})();