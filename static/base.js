$('#logoutLink') .click(logout);
$('.sidebarTitle') .click(slideMenu);
$('.quickAccessJobs') .click(function() {window.open('JobList.html?langID='+$('#languageAccessJobs').val()+'&prodID='+$('#productAccessJobs').val(), '_self', false);return false;});
$('#termSearch') .keyup(quickAccessTerms);
$('.quickAccessTerms') .click(quickAccessTerms);
$('.quickAccessTermsClear') .click(function() {$('#languageAccessTerms').val(0); $('#productAccessTerms').val(0); $('#termSearch').val(""); return false;});
$('.tbxExportTerms') .click(function() {window.open('terminology.tbx?langID='+$('#tbxExportLanguage').val()+'&prodID='+$('#tbxExportProduct').val(), '_self', false);return false;});

function quickAccessTerms(evt) {
	if (evt.type == 'keyup') {
		if (evt.keyCode==13 || evt.which==13) {
			window.open('TermList.html?langID='+$('#languageAccessTerms').val()+'&prodID='+$('#productAccessTerms').val()+($('#termSearch').val() ? "&search="+encodeURIComponent($('#termSearch').val()) : ""), '_self', false);
		}
	} else {
			window.open('TermList.html?langID='+$('#languageAccessTerms').val()+'&prodID='+$('#productAccessTerms').val()+($('#termSearch').val() ? "&search="+encodeURIComponent($('#termSearch').val()) : ""), '_self', false);
	}
	return false;
}

function logout(evt) {
	$.ajax({
		url: "logout",
		type: "GET",
		cache: false,
		processData: false,
		contentType: 'text/plain; charset=utf-8',
		success: function(text) {
			if ($('body').find('.loginForm').length === 0) {
				$(evt.target).parent().replaceWith('<div class="userDetails"><a href="#" id="loginLink">login</a></div>');
			} else {
				window.open('index.html', '_self', false);
			}
		},
		error: function(xhr, status) {
		},
		complete: function(xhr, status) {
		}
	});
	return false;
}

function slideMenu(evt) {
	$(evt.target).parentsUntil('ul').find('.sidebarContent').slideToggle();
	return false;
}