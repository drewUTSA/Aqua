// Provider UI protocol simulation, never a Google request or real credential.
export const googleStub = `(() => {
  let settings;
  window.google={accounts:{id:{initialize(value){settings=value;window.__fixtureGoogleSettings=value},disableAutoSelect(){},
    renderButton(container){const button=document.createElement('button');button.type='button';button.textContent='Continue with Google';
      button.onclick=()=>{
        if(settings.ux_mode!=='redirect'){settings.callback({credential:'fixture-google-credential'});return}
        if(!window.__fixtureOmitGoogleCookie)document.cookie='g_csrf_token=fixture-google-csrf; Path=/; SameSite=Lax';
        const form=document.createElement('form');form.method='POST';form.action=settings.login_uri;
        for(const [name,value] of Object.entries({credential:'fixture-google-credential',g_csrf_token:'fixture-google-csrf',client_id:settings.client_id})){
          const input=document.createElement('input');input.type='hidden';input.name=name;input.value=value;form.append(input)}
        document.body.append(form);form.submit();
      };container.append(button)}
  }}};
})();`;
