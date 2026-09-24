const fs=require('fs');const src=fs.readFileSync(process.argv[2],'utf8');
const pick=(name)=>{const i=src.indexOf(name);let d=0,j=src.indexOf('{',i);for(let k=j;k<src.length;k++){if(src[k]=='{')d++;else if(src[k]=='}'){d--;if(!d)return src.slice(src.lastIndexOf('\n',i)+1,k+1);}}};
eval('var CHOICE_CONTEXT=[];'+pick('function chooseCommaRow')+pick('function chooseComboboxOption'));
const O=t=>t.map(x=>({textContent:x}));
const cases=[
 [['Chicago Heights, Illinois, United States','Chicago, Illinois, United States','Chicago, Ohio, United States'],'Chicago, Illinois','Chicago','Chicago, Illinois, United States',[]],
 [['Baltimore Highlands, Baltimore, MD','Baltimore, Anne Arundel, MD','Baltimore, Baltimore City, MD','Baltimore, Fairfield, OH'],'Baltimore','Baltimore','Baltimore, Baltimore City, MD',['baltimore city','maryland','md','21210']],
 [['21210, Baltimore, Baltimore (Ind City), MD','21210, Baltimore, Baltimore City, MD'],'21210','21210',null,['maryland','md','21210']],
 [['Yes','No'],'No','No','No',[]],
 [['Norfolk Island +672','United States +1'],'No','No',null,[]],
 [['United States +1','Canada +1'],'United States','United States','United States +1',[]],
];
for(const [rows,w,t,exp,ctx] of cases){CHOICE_CONTEXT=ctx;const r=chooseComboboxOption(O(rows),w,t);const got=r?r.text:null;if(got!==exp){console.log('BAD',w,'->',got);process.exitCode=1;}}
