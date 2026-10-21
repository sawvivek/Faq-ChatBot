(function(){var t=null;try{t=localStorage.getItem("theme")}catch(e){}
if(t){document.documentElement.dataset.theme=t}
else if(window.matchMedia&&matchMedia("(prefers-color-scheme: dark)").matches){document.documentElement.dataset.theme="dark"}})();
