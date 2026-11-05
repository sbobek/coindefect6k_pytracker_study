#!/usr/bin/env python3
"""Prepare and run one isolated CoinDefect6k Tobii-PyTracker study."""
from __future__ import annotations
import argparse,csv,hashlib,json,os,random,re,shutil,subprocess,sys,urllib.request,zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ID_RE=re.compile(r"cd6k_([0-9a-f]{12})__",re.I)
IMG_EXT={'.jpg','.jpeg','.png','.bmp','.tif','.tiff','.webp'}
DATASETS={
 'manufacturing':{'archive':'dataset_public_manufacturing_defects.zip','dirname':'dataset_public_manufacturing_defects','url':'https://zenodo.org/api/records/18773634/files/dataset_public_manufacturing_defects.zip/content','marker':'manufacturing'},
 'circulation':{'archive':'dataset_public_circulation_quality.zip','dirname':'dataset_public_circulation_quality','url':'https://zenodo.org/api/records/18773634/files/dataset_public_circulation_quality.zip/content','marker':'circulation'},
}
@dataclass(frozen=True)
class Sample: source:Path; relative:str; split:str; label:str; sample_id:str

def resolution(v):
 m=re.fullmatch(r'\s*(\d+)\s*[xX]\s*(\d+)\s*',v)
 if not m or min(map(int,m.groups()))<1: raise argparse.ArgumentTypeError('resolution must be WIDTHxHEIGHT, e.g. 800x600')
 return tuple(map(int,m.groups()))
def args():
 p=argparse.ArgumentParser(description=__doc__); p.add_argument('--dataset',choices=DATASETS,required=True); p.add_argument('--samples',type=int,required=True); p.add_argument('--resolution',type=resolution,required=True,metavar='WIDTHxHEIGHT'); p.add_argument('--seed',type=int,default=42); p.add_argument('--data-dir',type=Path,default=Path('data')); p.add_argument('--output-dir',type=Path,default=Path('output')); p.add_argument('--config',type=Path,default=Path('configs/config.yaml')); p.add_argument('--eyetracker-config',type=Path,default=Path('configs/mouse_eyetracker_config.yaml')); p.add_argument('--physical-eyetracker',action='store_true'); p.add_argument('--enable_voice',action='store_true'); p.add_argument('--prepare-only',action='store_true'); p.add_argument('--force-redownload',action='store_true'); return p.parse_args()
def has_images(p): return p.is_dir() and any(x.is_file() and x.suffix.lower() in IMG_EXT for x in p.rglob('*'))
def extract(z,d):
 d.mkdir(parents=True,exist_ok=True); base=d.resolve()
 with zipfile.ZipFile(z) as f:
  for x in f.infolist():
   target=(d/x.filename).resolve()
   if os.path.commonpath([str(base),str(target)])!=str(base): raise RuntimeError(f'Unsafe archive member: {x.filename}')
  f.extractall(d)
def ensure_dataset(kind,data,force):
 s=DATASETS[kind]; root=data/'source'/s['dirname']
 if has_images(root) and not force: print(f'Using isolated {kind} source: {root}'); return root
 arc=data/'archives'/s['archive']
 if force or not arc.exists():
  arc.parent.mkdir(parents=True,exist_ok=True); tmp=arc.with_suffix(arc.suffix+'.part'); print(f'Downloading {kind} dataset')
  with urllib.request.urlopen(s['url']) as r,tmp.open('wb') as w: shutil.copyfileobj(r,w,1024*1024)
  tmp.replace(arc)
 if root.exists(): shutil.rmtree(root)
 extract(arc,root)
 if not has_images(root): raise RuntimeError(f'No images in {root}')
 return root
def index_samples(root,kind):
 # IMPORTANT: root is the selected variant directory only. Never index data/source globally.
 out=[]; expected=DATASETS[kind]['marker']
 for p in sorted(root.rglob('*')):
  if not p.is_file() or p.suffix.lower() not in IMG_EXT: continue
  rel=p.relative_to(root); parts=[x.lower() for x in rel.parts]; label=next((x for x in reversed(parts[:-1]) if x in {'good','bad'}),None)
  if not label: continue
  text=rel.as_posix(); split=next((x for x in parts if x in {'train','test','val','validation'}),'unspecified')
  # Include variant in ID so identical relative paths across datasets cannot collide.
  sid=hashlib.sha256(f'{kind}:{text}'.encode()).hexdigest()[:12]; out.append(Sample(p,text,split,label,sid))
 if not out: raise RuntimeError(f'No good/bad images found in selected {kind} root {root}')
 return out
def ids(v): return {m.group(1).lower() for m in ID_RE.finditer(str(v or ''))}
def completed(output):
 done=set(); files=sorted(output.rglob('data.csv')) if output.exists() else []
 for p in files:
  try:
   with p.open(encoding='utf-8-sig',newline='') as f:
    head=f.read(8192); f.seek(0)
    try: dialect=csv.Sniffer().sniff(head,delimiters=';,\t')
    except csv.Error: dialect=csv.excel; dialect.delimiter=';'
    for row in csv.DictReader(f,dialect=dialect): done|=ids(row.get('input_data'))|ids(row.get('screenshot_file'))
  except (OSError,UnicodeError,csv.Error) as e: print(f'Warning: cannot read {p}: {e}',file=sys.stderr)
 print(f'Analyzed {len(files)} {output.name} study data.csv file(s).'); return done
def current_ids(p): return set().union(*(ids(x.name) for x in p.rglob('*') if x.is_file() and x.suffix.lower() in IMG_EXT)) if p.exists() else set()
def choose(samples,done,n,seed):
 remain=[s for s in samples if s.sample_id not in done]
 if n<1: raise ValueError('--samples must be at least 1')
 if n>len(remain): raise ValueError(f'Requested {n}, only {len(remain)} unprocessed samples remain in this dataset')
 rng=random.Random(seed); groups=defaultdict(list)
 for s in remain: groups[s.label].append(s)
 for g in groups.values(): rng.shuffle(g)
 labels=sorted(groups); base,extra=divmod(n,len(labels)); need={x:base+(i<extra) for i,x in enumerate(labels)}
 if all(len(groups[x])>=need[x] for x in labels): selected=[s for x in labels for s in groups[x][:need[x]]]; mode='stratified'
 else: selected=remain[:]; rng.shuffle(selected); selected=selected[:n]; mode='fallback-unstratified'
 rng.shuffle(selected); return selected,mode
def populate(selected,target,kind,seed,mode):
 if target.exists(): shutil.rmtree(target)
 target.mkdir(parents=True); rows=[]
 for i,s in enumerate(selected):
  d=target/s.label; d.mkdir(exist_ok=True); dest=d/f"cd6k_{s.sample_id}__{re.sub(r'[^A-Za-z0-9._-]+','_',s.source.name)}"; shutil.copy2(s.source,dest)
  rows.append({'presentation_order':i,'sample_id':s.sample_id,'dataset':kind,'label':s.label,'source_split':s.split,'source_relative_path':s.relative,'study_relative_path':dest.relative_to(target.parent.parent).as_posix()})
 manifest=target/'selection_manifest.csv'
 with manifest.open('w',encoding='utf-8',newline='') as f: w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
 (target/'selection_metadata.json').write_text(json.dumps({'dataset':kind,'seed':seed,'new_samples':len(selected),'sampling_mode':mode},indent=2),encoding='utf-8'); return manifest
def patch_config(path,dataset,output,screen):
 text=path.read_text(encoding='utf-8'); text,np=re.subn(r'(?m)^(\s*path:\s*).*$',rf'\g<1>{dataset.resolve().as_posix()}',text,count=1); text,nr=re.subn(r'(?ms)^(\s*resolution:\s*)\n\s*-\s*\d+\s*\n\s*-\s*\d+\s*$',lambda m:f'{m.group(1)}\n      - {screen[0]}\n      - {screen[1]}',text,count=1); text,nf=re.subn(r'(?m)^(\s*folder:\s*).*$',rf'\g<1>{output.resolve().as_posix()}',text,count=1)
 if (np,nr,nf)!=(1,1,1): raise RuntimeError(f'Could not patch {path}')
 path.write_text(text,encoding='utf-8')
def main():
 a=args(); source=ensure_dataset(a.dataset,a.data_dir,a.force_redownload); samples=index_samples(source,a.dataset)
 # Separate history and new sessions by dataset variant.
 variant_output=a.output_dir/a.dataset; done=completed(variant_output); study=a.data_dir/'study_dataset'/a.dataset
 overlap=current_ids(study)&done
 if overlap: print(f'Current {a.dataset} study has {len(overlap)} processed samples; rebuilding it.')
 selected,mode=choose(samples,done,a.samples,a.seed); manifest=populate(selected,study,a.dataset,a.seed,mode); patch_config(a.config,study,variant_output,a.resolution)
 counts=defaultdict(int)
 for s in selected: counts[s.label]+=1
 print(f'Dataset: {a.dataset}; source: {source}; output: {variant_output}'); print(f'Indexed {len(samples)} {a.dataset} images; {len(done)} processed in this dataset.'); print(f'Prepared {len(selected)} ({mode}): {dict(counts)}'); print(f'Manifest: {manifest}')
 if a.prepare_only:return 0
 tracker=Path('configs/eyetracker_config.yaml') if a.physical_eyetracker else a.eyetracker_config; cmd=['tobii-pytracker','--config_file',str(a.config),'--eyetracker_config_file',str(tracker),'--loop_count',str(len(selected)),'--enable_eyetracker']
 if a.enable_voice:cmd.append('--enable_voice')
 print('Launching:',' '.join(cmd)); return subprocess.run(cmd,check=False).returncode
if __name__=='__main__':
 try: raise SystemExit(main())
 except (OSError,ValueError,RuntimeError,zipfile.BadZipFile) as e: print(f'Error: {e}',file=sys.stderr); raise SystemExit(2)
